#!/usr/bin/env python3
"""
Orthanc DICOM Modality Worklist (MWL) Dynamic Python Plugin
===========================================================
Intercepts incoming DICOM C-FIND Modality Worklist queries dynamically,
translates filters to an HTTP GET request to the .NET Core RIS API,
and returns scheduled examinations back to the requesting modality.

Integration Flow:
    Modality (C-FIND) ---> Orthanc PACS ---> Python Plugin ---> .NET Core RIS API (PostgreSQL)
                           Orthanc PACS <--- Python Plugin <--- JSON (Scheduled Exams)
    Modality (C-FIND-RSP) <--- Orthanc PACS
"""

import json
import os
import sys
import logging
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.exceptions import RequestException, Timeout, ConnectionError

# Configure local logger fallback
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [MWL_PLUGIN] %(message)s"
)
logger = logging.getLogger("MWL_PLUGIN")

# Try importing the official Orthanc Python SDK module
try:
    import orthanc
    HAS_ORTHANC = True
except ImportError:
    HAS_ORTHANC = False
    logger.warning("Orthanc Python SDK module ('orthanc') not found. Running in standalone/testing mode.")

# Configuration & Environment Defaults
RIS_API_BASE_URL = os.environ.get("RIS_API_URL", "http://host.docker.internal:5000/api/worklist")
HTTP_TIMEOUT_SECONDS = float(os.environ.get("RIS_API_TIMEOUT", "5.0"))


def log_info(msg: str) -> None:
    """Logs informational message to Orthanc and standard output."""
    if HAS_ORTHANC and hasattr(orthanc, "LogInfo"):
        orthanc.LogInfo(f"[MWL] {msg}")
    else:
        logger.info(msg)


def log_warning(msg: str) -> None:
    """Logs warning message to Orthanc and standard output."""
    if HAS_ORTHANC and hasattr(orthanc, "LogWarning"):
        orthanc.LogWarning(f"[MWL] {msg}")
    else:
        logger.warning(msg)


def log_error(msg: str) -> None:
    """Logs error message to Orthanc and standard error."""
    if HAS_ORTHANC and hasattr(orthanc, "LogError"):
        orthanc.LogError(f"[MWL] {msg}")
    else:
        logger.error(msg)


def parse_query_payload(query: Any) -> Dict[str, Any]:
    """
    Safely normalizes incoming query into a Python dictionary.
    Handles JSON strings, raw dicts, or Orthanc WorklistQuery objects.
    """
    if isinstance(query, dict):
        return query

    if isinstance(query, str):
        try:
            return json.loads(query)
        except json.JSONDecodeError as err:
            log_error(f"Failed to decode query JSON string: {err}. Raw string: {query[:200]}")
            return {}

    # Orthanc SDK WorklistQuery object fallback
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

    log_warning(f"Unknown query payload type '{type(query)}'. Attempting string conversion.")
    try:
        return json.loads(str(query))
    except Exception:
        return {}


def extract_filter_tag(dataset: Dict[str, Any], tag_hex: str, tag_name: str) -> Optional[str]:
    """
    Safely retrieves a DICOM tag value checking comma-hex ('0008,0060'),
    raw-hex ('00080060'), or friendly name ('Modality').
    """
    if not isinstance(dataset, dict):
        return None

    val = dataset.get(tag_hex)
    if val is None:
        val = dataset.get(tag_hex.replace(",", ""))
    if val is None:
        val = dataset.get(tag_name)

    if val is not None:
        # Handle dict or string value
        if isinstance(val, dict) and "Value" in val:
            val = val["Value"]
        if isinstance(val, list) and len(val) > 0:
            val = val[0]
        cleaned = str(val).strip()
        return cleaned if cleaned else None

    return None


def extract_modality_and_date(query_dict: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """
    Extracts Modality and Scheduled Procedure Step Start Date from:
    1. ScheduledProcedureStepSequence ('0040,0100')
    2. Root-level tags as fallback.
    """
    modality: Optional[str] = None
    scheduled_date: Optional[str] = None

    # 1. Search inside Scheduled Procedure Step Sequence (0040,0100)
    sps_seq = (
        query_dict.get("0040,0100")
        or query_dict.get("00400100")
        or query_dict.get("ScheduledProcedureStepSequence")
    )

    if sps_seq and isinstance(sps_seq, list) and len(sps_seq) > 0:
        first_sps = sps_seq[0]
        if isinstance(first_sps, dict):
            # Extract Modality (0008,0060)
            modality = extract_filter_tag(first_sps, "0008,0060", "Modality")
            # Extract Scheduled Procedure Step Start Date (0040,0002)
            scheduled_date = extract_filter_tag(first_sps, "0040,0002", "ScheduledProcedureStepStartDate")

    # 2. Fallbacks: Check root-level tags if not found in sequence
    if not modality:
        modality = extract_filter_tag(query_dict, "0008,0060", "Modality")

    if not scheduled_date:
        scheduled_date = (
            extract_filter_tag(query_dict, "0040,0002", "ScheduledProcedureStepStartDate")
            or extract_filter_tag(query_dict, "0008,0020", "StudyDate")
        )

    # Clean wildcards and date ranges
    if modality and modality in ("*", "?", ""):
        modality = None

    if scheduled_date:
        scheduled_date = scheduled_date.strip()
        if scheduled_date in ("*", "?", ""):
            scheduled_date = None
        elif "-" in scheduled_date:
            # Handle standard DICOM range (e.g. '20261022-20261022' or '20261022-')
            parts = scheduled_date.split("-")
            scheduled_date = parts[0].strip() if parts[0].strip() else parts[1].strip()

    return modality, scheduled_date


def query_ris_api(modality: Optional[str], scheduled_date: Optional[str]) -> List[Dict[str, Any]]:
    """
    Performs synchronous HTTP GET to .NET Core RIS API.
    Handles network errors, non-200 responses, and timeouts gracefully.
    """
    params: Dict[str, str] = {}
    if modality:
        params["modality"] = modality
    if scheduled_date:
        params["date"] = scheduled_date

    log_info(f"Querying RIS API at '{RIS_API_BASE_URL}' with params: {params}")

    try:
        response = requests.get(
            RIS_API_BASE_URL,
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
            else:
                log_warning(f"Unexpected non-array response from RIS API: {type(data)}")
                return []
        else:
            log_error(
                f"RIS API HTTP {response.status_code} error: {response.text[:300]}"
            )
            return []

    except Timeout:
        log_error(f"Timeout ({HTTP_TIMEOUT_SECONDS}s) querying RIS API at '{RIS_API_BASE_URL}'.")
        return []
    except ConnectionError as ce:
        log_error(f"Failed to connect to RIS API at '{RIS_API_BASE_URL}': {ce}")
        return []
    except RequestException as re:
        log_error(f"HTTP request exception communicating with RIS API: {re}")
        return []
    except Exception as ex:
        log_error(f"Unexpected error querying RIS API: {ex}")
        return []


def worklist_callback(*args, **kwargs) -> None:
    """
    Orthanc Modality Worklist C-FIND Callback handler.
    Supports standard (answers, query, issuerAet, calledAet) arguments.
    """
    # Unpack arguments flexibly across Orthanc versions
    answers = None
    query = None
    issuer_aet = ""
    called_aet = ""

    if len(args) == 4:
        # Standard: (answers, query, issuerAet, calledAet)
        answers, query, issuer_aet, called_aet = args
    elif len(args) == 3:
        # RegisterWorklistCallback2: (connection, answers, query)
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
        # 1. Parse incoming query
        query_dict = parse_query_payload(query)

        # 2. Extract Modality and Date filters safely from ScheduledProcedureStepSequence
        modality, scheduled_date = extract_modality_and_date(query_dict)
        log_info(f"Extracted MWL Search Filters -> Modality: '{modality or 'ANY'}', Date: '{scheduled_date or 'TODAY'}'")

        # 3. Synchronous HTTP GET to .NET Core API
        scheduled_exams = query_ris_api(modality, scheduled_date)

        # 4 & 5. Loop through JSON items, serialize to JSON string, and append to answers
        for item in scheduled_exams:
            item_json_str = json.dumps(item)

            # Defensive append supporting both Python list and Orthanc C++ SDK answers
            if isinstance(answers, list):
                # Spec requirement: append JSON string format to answers list
                answers.append(item_json_str)
            elif HAS_ORTHANC and hasattr(answers, "WorklistAddAnswer"):
                # Convert JSON string to binary DICOM dataset using Orthanc SDK
                dicom_bytes = orthanc.CreateDicom(item_json_str, None, orthanc.CreateDicomFlags.NONE)
                answers.WorklistAddAnswer(query, dicom_bytes)
            elif hasattr(answers, "append"):
                answers.append(item_json_str)
            else:
                log_warning(f"Unrecognized answers collection type: {type(answers)}")

        log_info(f"Successfully supplied {len(scheduled_exams)} worklist match(es) to '{issuer_aet}'.")

    except Exception as ex:
        # Safe error boundary: never raise unhandled exceptions out of C-FIND callback
        log_error(f"Critical error in worklist callback execution: {ex}")


# Register callback with Orthanc
if HAS_ORTHANC:
    try:
        orthanc.RegisterWorklistCallback(worklist_callback)
        log_info("Successfully registered dynamic Worklist callback via orthanc.RegisterWorklistCallback().")
    except Exception as err:
        log_error(f"Failed to register Orthanc Worklist callback: {err}")
else:
    logger.info("Plugin loaded outside Orthanc environment. Callback registration skipped.")


if __name__ == "__main__":
    # Self-test mode when run directly via CLI
    print("=== Testing Orthanc Worklist Plugin Logic Locally ===")
    test_query = {
        "0040,0100": [
            {
                "0008,0060": "CT",
                "0040,0002": "20261022"
            }
        ]
    }
    m, d = extract_modality_and_date(test_query)
    print(f"Extracted Modality: {m}, Date: {d}")
    print("Plugin script syntax and imports verified successfully.")
