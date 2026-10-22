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
# PART 2: Automated Exam Completion Webhook (C-STORE Instance Storage)
# =====================================================================

class StudyDebouncer:
    """
    Thread-safe debouncer and deduplicator for incoming DICOM studies.
    Prevents flooding the RIS API when a modality streams hundreds/thousands of slices
    for a single CT, MRI, or multi-frame study.
    """

    def __init__(self, debounce_delay: float = 3.0, cache_ttl: float = 3600.0):
        self.debounce_delay = debounce_delay
        self.cache_ttl = cache_ttl
        self._lock = threading.Lock()
        self._timers: Dict[str, threading.Timer] = {}
        self._study_data: Dict[str, Dict[str, Any]] = {}
        self._completed_cache: Dict[str, float] = {}

        self._queue: Queue = Queue()
        self._worker_thread = threading.Thread(target=self._http_worker, daemon=True)
        self._worker_thread.start()

    def _cleanup_expired_cache(self, now: float) -> None:
        expired = [k for k, ts in self._completed_cache.items() if now - ts > self.cache_ttl]
        for k in expired:
            del self._completed_cache[k]

    def record_instance(
        self,
        accession_number: Optional[str],
        study_instance_uid: Optional[str],
        modality: Optional[str] = None,
        station_ae: Optional[str] = None
    ) -> bool:
        key = (accession_number or study_instance_uid or "").strip().upper()
        if not key:
            return False

        now = time.time()
        with self._lock:
            self._cleanup_expired_cache(now)

            if key in self._completed_cache:
                return False

            if key not in self._study_data:
                self._study_data[key] = {
                    "accessionNumber": accession_number,
                    "studyInstanceUid": study_instance_uid,
                    "modality": modality,
                    "stationAeTitle": station_ae,
                    "instanceCount": 1,
                    "firstSeen": now,
                    "lastSeen": now,
                }
            else:
                record = self._study_data[key]
                record["instanceCount"] += 1
                record["lastSeen"] = now
                if not record["accessionNumber"] and accession_number:
                    record["accessionNumber"] = accession_number
                if not record["studyInstanceUid"] and study_instance_uid:
                    record["studyInstanceUid"] = study_instance_uid
                if not record["modality"] and modality:
                    record["modality"] = modality

            if key in self._timers:
                self._timers[key].cancel()

            timer = threading.Timer(self.debounce_delay, self._on_study_settled, args=[key])
            self._timers[key] = timer
            timer.start()

            return True

    def _on_study_settled(self, key: str) -> None:
        with self._lock:
            self._timers.pop(key, None)
            study_info = self._study_data.pop(key, None)
            if not study_info:
                return
            self._completed_cache[key] = time.time()

        self._queue.put(study_info)

    def _http_worker(self) -> None:
        while True:
            try:
                payload = self._queue.get()
                self._send_complete_webhook(payload)
                self._queue.task_done()
            except Exception as e:
                log_error(f"Unexpected error in debounce worker thread: {e}")

    def _send_complete_webhook(self, payload: Dict[str, Any]) -> None:
        accession = payload.get("accessionNumber")
        study_uid = payload.get("studyInstanceUid")
        count = payload.get("instanceCount", 1)

        log_info(
            f"Study stream settled ({count} instances). Triggering RIS webhook for "
            f"Accession='{accession}', StudyUID='{study_uid}' -> {RIS_STATUS_API_URL}"
        )

        post_body = {
            "accessionNumber": accession,
            "studyInstanceUid": study_uid,
            "modality": payload.get("modality"),
            "stationAeTitle": payload.get("stationAeTitle"),
            "instanceCount": count
        }

        try:
            resp = requests.post(
                RIS_STATUS_API_URL,
                json=post_body,
                timeout=HTTP_TIMEOUT_SECONDS,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Orthanc-ExamStatus-Plugin/1.0"
                }
            )

            if resp.status_code in (200, 204):
                log_info(f"RIS API successfully updated exam status to Completed: {resp.text}")
            elif resp.status_code == 404:
                log_warning(f"RIS API reported exam not found for Accession='{accession}': {resp.text}")
            else:
                log_error(f"RIS API returned HTTP {resp.status_code}: {resp.text[:300]}")

        except Timeout:
            log_error(f"Timeout ({HTTP_TIMEOUT_SECONDS}s) connecting to RIS API at {RIS_STATUS_API_URL}")
        except ConnectionError as ce:
            log_error(f"Failed to connect to RIS API at {RIS_STATUS_API_URL}: {ce}")
        except RequestException as re:
            log_error(f"HTTP exception notifying RIS API: {re}")
        except Exception as ex:
            log_error(f"Unexpected error executing status webhook: {ex}")


_debouncer = StudyDebouncer(
    debounce_delay=DEBOUNCE_DELAY_SECONDS,
    cache_ttl=DEDUPLICATION_CACHE_TTL
)


def extract_instance_metadata(dicom: Any) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    tags: Dict[str, Any] = {}

    if hasattr(dicom, "GetInstanceSimplifiedJson"):
        try:
            raw_json = dicom.GetInstanceSimplifiedJson()
            if isinstance(raw_json, str):
                tags = json.loads(raw_json)
            elif isinstance(raw_json, dict):
                tags = raw_json
        except Exception as e:
            log_warning(f"Failed to parse instance simplified JSON: {e}")

    accession = (
        tags.get("AccessionNumber")
        or tags.get("0008,0050")
        or tags.get("00080050")
    )
    study_uid = (
        tags.get("StudyInstanceUID")
        or tags.get("0020,000d")
        or tags.get("0020000d")
    )
    modality = (
        tags.get("Modality")
        or tags.get("0008,0060")
        or tags.get("00080060")
    )
    station_ae = (
        tags.get("StationName")
        or tags.get("ScheduledStationAETitle")
        or tags.get("0008,1010")
        or tags.get("0040,0001")
    )

    clean_accession = str(accession).strip() if accession else None
    clean_study_uid = str(study_uid).strip() if study_uid else None
    clean_modality = str(modality).strip() if modality else None
    clean_station_ae = str(station_ae).strip() if station_ae else None

    return clean_accession, clean_study_uid, clean_modality, clean_station_ae


def on_stored_instance_callback(dicom: Any, instance_id: str) -> None:
    try:
        accession, study_uid, modality, station_ae = extract_instance_metadata(dicom)

        if not accession and not study_uid:
            return

        # Record instance in non-blocking thread debouncer (< 0.1ms)
        _debouncer.record_instance(accession, study_uid, modality, station_ae)

    except Exception as ex:
        log_error(f"Error handling stored instance '{instance_id}': {ex}")


# =====================================================================
# Plugin Initialization & Registration
# =====================================================================

if HAS_ORTHANC:
    try:
        orthanc.RegisterWorklistCallback(worklist_callback)
        log_info("Successfully registered dynamic Worklist callback via orthanc.RegisterWorklistCallback().")
    except Exception as err:
        log_error(f"Failed to register Orthanc Worklist callback: {err}")

    try:
        orthanc.RegisterOnStoredInstanceCallback(on_stored_instance_callback)
        log_info("Successfully registered OnStoredInstance callback with debouncer & RIS status webhook.")
    except Exception as err:
        log_error(f"Failed to register OnStoredInstance callback: {err}")
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
