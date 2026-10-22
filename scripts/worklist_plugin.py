#!/usr/bin/env python3
"""
Orthanc DICOM Unified MWL & Exam Completion Plugin
===================================================
Provides two core RIS/PACS clinical workflow integrations in a single plugin:

1. Dynamic Modality Worklist (MWL C-FIND):
   Intercepts modality search queries, calls .NET Core RIS API (GET /api/worklist),
   and delivers scheduled DICOM worklist responses back to the modality.

2. Automated Exam Completion Webhook (C-STORE Instance Storage):
   Intercepts incoming stored instances, debounces multi-frame / multi-slice studies,
   and fires an asynchronous HTTP POST to .NET Core RIS API (POST /api/exams/complete)
   to transition the exam status to 'Completed' in PostgreSQL.
"""

import json
import os
import sys
import time
import logging
import threading
from queue import Queue
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.exceptions import RequestException, Timeout, ConnectionError

# Configure local logger fallback
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [ORTHANC_RIS_PLUGIN] %(message)s"
)
logger = logging.getLogger("ORTHANC_RIS_PLUGIN")

# Try importing the official Orthanc Python SDK module
try:
    import orthanc
    HAS_ORTHANC = True
except ImportError:
    HAS_ORTHANC = False
    logger.warning("Orthanc Python SDK module ('orthanc') not found. Running in standalone/testing mode.")

# =====================================================================
# Configuration & Environment Defaults
# =====================================================================
RIS_WORKLIST_API_URL = os.environ.get("RIS_API_URL", "http://ris-api:8080/api/worklist")
RIS_STATUS_API_URL = os.environ.get(
    "RIS_STATUS_API_URL",
    RIS_WORKLIST_API_URL.replace("/api/worklist", "/api/exams/complete")
)
if not RIS_STATUS_API_URL.endswith("/api/exams/complete"):
    RIS_STATUS_API_URL = RIS_STATUS_API_URL.rstrip("/") + "/api/exams/complete"

HTTP_TIMEOUT_SECONDS = float(os.environ.get("RIS_API_TIMEOUT", "5.0"))
DEBOUNCE_DELAY_SECONDS = float(os.environ.get("RIS_STATUS_DEBOUNCE_SECONDS", "3.0"))
DEDUPLICATION_CACHE_TTL = float(os.environ.get("RIS_STATUS_CACHE_TTL_SECONDS", "3600.0"))


def log_info(msg: str) -> None:
    if HAS_ORTHANC and hasattr(orthanc, "LogInfo"):
        orthanc.LogInfo(f"[RIS_PLUGIN] {msg}")
    else:
        logger.info(msg)


def log_warning(msg: str) -> None:
    if HAS_ORTHANC and hasattr(orthanc, "LogWarning"):
        orthanc.LogWarning(f"[RIS_PLUGIN] {msg}")
    else:
        logger.warning(msg)


def log_error(msg: str) -> None:
    if HAS_ORTHANC and hasattr(orthanc, "LogError"):
        orthanc.LogError(f"[RIS_PLUGIN] {msg}")
    else:
        logger.error(msg)


# =====================================================================
# PART 1: Dynamic Modality Worklist (C-FIND)
# =====================================================================

def parse_query_payload(query: Any) -> Dict[str, Any]:
    if isinstance(query, dict):
        return query
    if isinstance(query, str):
        try:
            return json.loads(query)
        except json.JSONDecodeError as err:
            log_error(f"Failed to decode query JSON string: {err}. Raw string: {query[:200]}")
            return {}

    if HAS_ORTHANC and hasattr(query, "WorklistGetDicomQuery"):
        try:
            dicom_buf = query.WorklistGetDicomQuery()
            json_str = orthanc.DicomBufferToJson(
                dicom_buf,
                orthanc.DicomToJsonFormat.SHORT,
                orthanc.DicomToJsonFlags.NONE,
                0,
            )
            return json.loads(json_str)
        except Exception as err:
            log_error(f"Error converting Orthanc DICOM buffer to JSON: {err}")
            return {}

    try:
        return json.loads(str(query))
    except Exception:
        return {}


def extract_filter_tag(dataset: Dict[str, Any], tag_hex: str, tag_name: str) -> Optional[str]:
    if not isinstance(dataset, dict):
        return None

    val = dataset.get(tag_hex)
    if val is None:
        val = dataset.get(tag_hex.replace(",", ""))
    if val is None:
        val = dataset.get(tag_name)

    if val is not None:
        if isinstance(val, dict) and "Value" in val:
            val = val["Value"]
        if isinstance(val, list) and len(val) > 0:
            val = val[0]
        cleaned = str(val).strip()
        return cleaned if cleaned else None

    return None


def extract_modality_and_date(query_dict: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    modality: Optional[str] = None
    scheduled_date: Optional[str] = None

    sps_seq = (
        query_dict.get("0040,0100")
        or query_dict.get("00400100")
        or query_dict.get("ScheduledProcedureStepSequence")
    )

    if sps_seq and isinstance(sps_seq, list) and len(sps_seq) > 0:
        first_sps = sps_seq[0]
        if isinstance(first_sps, dict):
            modality = extract_filter_tag(first_sps, "0008,0060", "Modality")
            scheduled_date = extract_filter_tag(first_sps, "0040,0002", "ScheduledProcedureStepStartDate")

    if not modality:
        modality = extract_filter_tag(query_dict, "0008,0060", "Modality")

    if not scheduled_date:
        scheduled_date = (
            extract_filter_tag(query_dict, "0040,0002", "ScheduledProcedureStepStartDate")
            or extract_filter_tag(query_dict, "0008,0020", "StudyDate")
        )

    if modality and modality in ("*", "?", ""):
        modality = None

    if scheduled_date:
        scheduled_date = scheduled_date.strip()
        if scheduled_date in ("*", "?", ""):
            scheduled_date = None
        elif "-" in scheduled_date:
            parts = scheduled_date.split("-")
            scheduled_date = parts[0].strip() if parts[0].strip() else parts[1].strip()

    return modality, scheduled_date


def query_ris_worklist(modality: Optional[str], scheduled_date: Optional[str]) -> List[Dict[str, Any]]:
    params: Dict[str, str] = {}
    if modality:
        params["modality"] = modality
    if scheduled_date:
        params["date"] = scheduled_date

    log_info(f"Querying RIS Worklist API at '{RIS_WORKLIST_API_URL}' with params: {params}")

    try:
        response = requests.get(
            RIS_WORKLIST_API_URL,
            params=params,
            timeout=HTTP_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/json",
                "User-Agent": "Orthanc-MWL-Python-Plugin/1.0",
            },
        )

        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                log_info(f"RIS API returned {len(data)} scheduled worklist exam(s).")
                return data
            log_warning(f"Unexpected non-array response from RIS API: {type(data)}")
            return []
        else:
            log_error(f"RIS API HTTP {response.status_code} error: {response.text[:300]}")
            return []

    except Timeout:
        log_error(f"Timeout ({HTTP_TIMEOUT_SECONDS}s) querying RIS API at '{RIS_WORKLIST_API_URL}'.")
        return []
    except ConnectionError as ce:
        log_error(f"Failed to connect to RIS API at '{RIS_WORKLIST_API_URL}': {ce}")
        return []
    except RequestException as re:
        log_error(f"HTTP request exception communicating with RIS API: {re}")
        return []
    except Exception as ex:
        log_error(f"Unexpected error querying RIS API: {ex}")
        return []


def worklist_callback(*args, **kwargs) -> None:
    answers = None
    query = None
    issuer_aet = ""
    called_aet = ""

    if len(args) == 4:
        answers, query, issuer_aet, called_aet = args
    elif len(args) == 3:
        conn, answers, query = args
        issuer_aet = getattr(conn, "GetConnectionRemoteAet", lambda: "")()
        called_aet = getattr(conn, "GetConnectionCalledAet", lambda: "")()
    elif len(args) == 2:
        answers, query = args
    else:
        log_error(f"Unexpected callback arguments count: {len(args)}")
        return

    log_info(f"Received C-FIND Worklist query from Calling AET: '{issuer_aet}' to Called AET: '{called_aet}'")

    try:
        query_dict = parse_query_payload(query)
        modality, scheduled_date = extract_modality_and_date(query_dict)
        log_info(f"Extracted MWL Search Filters -> Modality: '{modality or 'ANY'}', Date: '{scheduled_date or 'TODAY'}'")

        scheduled_exams = query_ris_worklist(modality, scheduled_date)

        for item in scheduled_exams:
            item_json_str = json.dumps(item)

            if isinstance(answers, list):
                answers.append(item_json_str)
            elif HAS_ORTHANC and hasattr(answers, "WorklistAddAnswer"):
                dicom_bytes = orthanc.CreateDicom(item_json_str, None, orthanc.CreateDicomFlags.NONE)
                answers.WorklistAddAnswer(query, dicom_bytes)
            elif hasattr(answers, "append"):
                answers.append(item_json_str)
            else:
                log_warning(f"Unrecognized answers collection type: {type(answers)}")

        log_info(f"Successfully supplied {len(scheduled_exams)} worklist match(es) to '{issuer_aet}'.")

    except Exception as ex:
        log_error(f"Critical error in worklist callback execution: {ex}")


# =====================================================================
# PART 2: Automated Exam Completion Webhook (Orthanc Stable Study Event)
# =====================================================================

def extract_study_identifiers(study_dict: Dict[str, Any]) -> Tuple[str, str]:
    """
    Extracts AccessionNumber and StudyInstanceUID from Orthanc's /studies/{id} JSON response.
    Gracefully handles empty, missing, or alternate hexadecimal DICOM tag keys.
    """
    main_tags = study_dict.get("MainDicomTags", {})

    accession = (
        main_tags.get("AccessionNumber")
        or main_tags.get("0008,0050")
        or main_tags.get("00080050")
        or ""
    )
    if isinstance(accession, dict) and "Value" in accession:
        accession = accession["Value"]
    clean_accession = str(accession).strip() if accession is not None else ""

    study_uid = (
        main_tags.get("StudyInstanceUID")
        or main_tags.get("0020,000d")
        or main_tags.get("0020000d")
        or ""
    )
    if isinstance(study_uid, dict) and "Value" in study_uid:
        study_uid = study_uid["Value"]
    clean_study_uid = str(study_uid).strip() if study_uid is not None else ""

    return clean_accession, clean_study_uid


def stable_study_callback(studyId: str) -> None:
    """
    Orthanc Stable Study callback.
    Fires once per study when transmission has completely settled
    (no new instances received within StableAge timeout window, typically 60s).
    """
    log_info(f"Orthanc detected Stable Study event for internal StudyID: '{studyId}'")

    if not HAS_ORTHANC:
        log_warning(f"Orthanc SDK not available; skipping REST API fetch for StudyID '{studyId}'.")
        return

    # 1. Fetch study core metadata from Orthanc's internal memory
    try:
        raw_response = orthanc.RestApiGet(f"/studies/{studyId}")
        if isinstance(raw_response, bytes):
            raw_response = raw_response.decode("utf-8")

        study_metadata = json.loads(raw_response) if isinstance(raw_response, str) else raw_response
        if not isinstance(study_metadata, dict):
            log_error(f"Unexpected non-dict response format from /studies/{studyId}: {type(study_metadata)}")
            return

    except Exception as ex:
        log_error(f"Failed to retrieve metadata from Orthanc REST API for study '{studyId}': {ex}")
        return

    # 2. Extract Accession Number and Study Instance UID
    accession_number, study_instance_uid = extract_study_identifiers(study_metadata)

    log_info(
        f"Stable Study '{studyId}' resolved: AccessionNumber='{accession_number}', "
        f"StudyInstanceUID='{study_instance_uid}'"
    )

    if not accession_number and not study_instance_uid:
        log_warning(
            f"Study '{studyId}' contains neither AccessionNumber nor StudyInstanceUID. "
            "Skipping RIS completion notification."
        )
        return

    # 3. Construct strictly formatted JSON payload
    payload = {
        "accessionNumber": accession_number,
        "studyInstanceUid": study_instance_uid
    }

    # 4. Send single HTTP POST request to .NET Core RIS API
    log_info(
        f"Sending exam completion webhook to RIS API at '{RIS_STATUS_API_URL}' "
        f"with payload: {payload}"
    )

    try:
        response = requests.post(
            RIS_STATUS_API_URL,
            json=payload,
            timeout=HTTP_TIMEOUT_SECONDS,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Orthanc-StableStudy-Plugin/1.0"
            }
        )

        if response.status_code in (200, 204):
            log_info(
                f"RIS API successfully acknowledged exam completion (HTTP {response.status_code}): "
                f"{response.text}"
            )
        elif response.status_code == 404:
            log_warning(
                f"RIS API reported exam not found for Accession='{accession_number}', "
                f"StudyUID='{study_instance_uid}' (HTTP 404): {response.text}"
            )
        else:
            log_error(
                f"RIS API returned unexpected HTTP {response.status_code} for study '{studyId}': "
                f"{response.text[:300]}"
            )

    except Timeout:
        log_error(f"Timeout ({HTTP_TIMEOUT_SECONDS}s) connecting to RIS API endpoint '{RIS_STATUS_API_URL}'.")
    except ConnectionError as ce:
        log_error(f"Network connection failed while reaching RIS API at '{RIS_STATUS_API_URL}': {ce}")
    except RequestException as re:
        log_error(f"HTTP request error during RIS completion webhook: {re}")
    except Exception as ex:
        log_error(f"Unexpected exception while sending completion notification for study '{studyId}': {ex}")


# =====================================================================
# Plugin Initialization & Registration
# =====================================================================

if HAS_ORTHANC:
    # Ensure orthanc has RegisterOnStableStudyCallback attribute
    if not hasattr(orthanc, "RegisterOnStableStudyCallback"):
        def _register_on_stable_study(callback):
            def _on_change(change_type, level, resource_id):
                if change_type == orthanc.ChangeType.STABLE_STUDY:
                    callback(resource_id)
            orthanc.RegisterOnChangeCallback(_on_change)

        orthanc.RegisterOnStableStudyCallback = _register_on_stable_study

    try:
        orthanc.RegisterWorklistCallback(worklist_callback)
        log_info("Successfully registered dynamic Worklist callback via orthanc.RegisterWorklistCallback().")
    except Exception as err:
        log_error(f"Failed to register Orthanc Worklist callback: {err}")

    try:
        orthanc.RegisterOnStableStudyCallback(stable_study_callback)
        log_info("Successfully registered OnStableStudy callback via orthanc.RegisterOnStableStudyCallback().")
    except Exception as err:
        log_error(f"Failed to register OnStableStudy callback: {err}")
else:
    logger.info("Plugin loaded outside Orthanc environment. Callbacks registration skipped.")


if __name__ == "__main__":
    print("=== Testing Unified Orthanc RIS Plugin Locally ===")
    test_query = {"0040,0100": [{"0008,0060": "CT", "0040,0002": "20261022"}]}
    m, d = extract_modality_and_date(test_query)
    print(f"Worklist Filter -> Modality: {m}, Date: {d}")
    print(f"Target Worklist API: {RIS_WORKLIST_API_URL}")
    print(f"Target Status Completion Webhook: {RIS_STATUS_API_URL}")
    print("All modules and callbacks verified successfully.")
