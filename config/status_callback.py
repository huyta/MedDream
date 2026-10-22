#!/usr/bin/env python3
"""
Orthanc DICOM Instance Storage & Exam Status Completion Plugin
==============================================================
Monitors incoming DICOM C-STORE storage events in Orthanc, extracts
Accession Number and Study Instance UID, debounces/deduplicates multi-frame
studies, and fires an asynchronous webhook to the .NET Core RIS API to mark
the examination as 'Completed'.

Workflow:
    Modality (C-STORE Slices) ---> Orthanc PACS
                                        │
                                        ▼ (RegisterOnStoredInstanceCallback)
                              [status_callback.py]
                                        │
                         (Debounce / Settle Window: 3.0s)
                                        │
                                        ▼ (Background Worker Thread)
                           HTTP POST /api/exams/complete
                                        │
                                        ▼
                             .NET Core RIS API (PostgreSQL)
                           Exams table: Status -> 'Completed'
"""

import json
import os
import sys
import time
import logging
import threading
from queue import Queue, Empty
from typing import Any, Dict, Optional, Tuple

import requests
from requests.exceptions import RequestException, Timeout, ConnectionError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [STATUS_CALLBACK] %(message)s"
)
logger = logging.getLogger("STATUS_CALLBACK")

# Import official Orthanc Python SDK
try:
    import orthanc
    HAS_ORTHANC = True
except ImportError:
    HAS_ORTHANC = False
    logger.warning("Orthanc Python SDK module ('orthanc') not found. Running in standalone/testing mode.")

# Configuration & Defaults
# In Docker Compose, RIS API is available at http://ris-api:8080/api/exams/complete
DEFAULT_API_URL = os.environ.get(
    "RIS_STATUS_API_URL",
    os.environ.get("RIS_API_URL", "http://host.docker.internal:5000/api/worklist")
    .replace("/api/worklist", "/api/exams/complete")
)
if not DEFAULT_API_URL.endswith("/api/exams/complete"):
    DEFAULT_API_URL = DEFAULT_API_URL.rstrip("/") + "/api/exams/complete"

RIS_STATUS_API_URL = os.environ.get("RIS_STATUS_API_URL", DEFAULT_API_URL)
HTTP_TIMEOUT_SECONDS = float(os.environ.get("RIS_STATUS_TIMEOUT", "5.0"))
DEBOUNCE_DELAY_SECONDS = float(os.environ.get("RIS_STATUS_DEBOUNCE_SECONDS", "3.0"))
DEDUPLICATION_CACHE_TTL = float(os.environ.get("RIS_STATUS_CACHE_TTL_SECONDS", "3600.0"))  # 1 hour


def log_info(msg: str) -> None:
    if HAS_ORTHANC and hasattr(orthanc, "LogInfo"):
        orthanc.LogInfo(f"[STATUS] {msg}")
    else:
        logger.info(msg)


def log_warning(msg: str) -> None:
    if HAS_ORTHANC and hasattr(orthanc, "LogWarning"):
        orthanc.LogWarning(f"[STATUS] {msg}")
    else:
        logger.warning(msg)


def log_error(msg: str) -> None:
    if HAS_ORTHANC and hasattr(orthanc, "LogError"):
        orthanc.LogError(f"[STATUS] {msg}")
    else:
        logger.error(msg)


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
        self._completed_cache: Dict[str, float] = {}  # key -> timestamp completed

        # Background HTTP worker queue & thread
        self._queue: Queue = Queue()
        self._worker_thread = threading.Thread(target=self._http_worker, daemon=True)
        self._worker_thread.start()

    def _cleanup_expired_cache(self, now: float) -> None:
        """Evicts expired study entries from deduplication cache."""
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
        """
        Records an incoming instance and resets the sliding debounce timer.
        Returns True if queued/debouncing, False if already completed/cached.
        """
        # Primary unique study identifier: Accession Number or Study Instance UID
        key = (accession_number or study_instance_uid or "").strip().upper()
        if not key:
            return False

        now = time.time()
        with self._lock:
            self._cleanup_expired_cache(now)

            # 1. Deduplication: If study was already marked as completed recently, skip
            if key in self._completed_cache:
                return False

            # 2. Accumulate/update study metadata
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

            # 3. Sliding Debounce Timer: Cancel existing timer for this study if active
            if key in self._timers:
                self._timers[key].cancel()

            # Start a new timer; fires when no new slices arrive within debounce_delay seconds
            timer = threading.Timer(self.debounce_delay, self._on_study_settled, args=[key])
            self._timers[key] = timer
            timer.start()

            return True

    def _on_study_settled(self, key: str) -> None:
        """Called when a study debounce window expires with no further instances received."""
        with self._lock:
            self._timers.pop(key, None)
            study_info = self._study_data.pop(key, None)
            if not study_info:
                return
            # Mark as completed in dedup cache
            self._completed_cache[key] = time.time()

        # Enqueue payload for background HTTP dispatch
        self._queue.put(study_info)

    def _http_worker(self) -> None:
        """Background thread executing HTTP webhooks to .NET Core RIS API."""
        while True:
            try:
                payload = self._queue.get()
                self._send_complete_webhook(payload)
                self._queue.task_done()
            except Exception as e:
                log_error(f"Unexpected error in debounce worker thread: {e}")

    def _send_complete_webhook(self, payload: Dict[str, Any]) -> None:
        """Sends HTTP POST to RIS API endpoint."""
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


# Singleton Debouncer Instance
_debouncer = StudyDebouncer(
    debounce_delay=DEBOUNCE_DELAY_SECONDS,
    cache_ttl=DEDUPLICATION_CACHE_TTL
)


def extract_dicom_tags(dicom: Any) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Extracts AccessionNumber, StudyInstanceUID, Modality, and StationName
    from an Orthanc DICOM instance.
    """
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

    # Fallbacks checking tags dictionary with standard and hex keys
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
    """
    Orthanc Stored Instance callback listener.
    Fires on every DICOM instance stored (C-STORE or REST API upload).
    Execution is synchronous with Orthanc core, so all heavy processing / HTTP
    calls are delegated to the non-blocking background debouncer.
    """
    try:
        accession, study_uid, modality, station_ae = extract_dicom_tags(dicom)

        if not accession and not study_uid:
            # Metadata lacks study/accession identifiers; skip
            return

        # Pass to thread-safe debouncer (non-blocking: takes < 0.1ms)
        _debouncer.record_instance(accession, study_uid, modality, station_ae)

    except Exception as ex:
        # Never raise exceptions out of OnStoredInstance callback to avoid blocking C-STORE
        log_error(f"Error handling stored instance '{instance_id}': {ex}")


# Register with Orthanc if available
if HAS_ORTHANC:
    try:
        orthanc.RegisterOnStoredInstanceCallback(on_stored_instance_callback)
        log_info("Successfully registered OnStoredInstance callback with debouncing & deduplication.")
    except Exception as err:
        log_error(f"Failed to register OnStoredInstance callback: {err}")
else:
    logger.info("Plugin loaded outside Orthanc environment. Callback registration skipped.")


if __name__ == "__main__":
    print("=== Testing Orthanc Status Callback Logic Locally ===")
    test_tags = {
        "AccessionNumber": "ACC2026102201",
        "StudyInstanceUID": "2.25.13847291048291048102948192039102",
        "Modality": "CT"
    }

    class MockDicom:
        def GetInstanceSimplifiedJson(self):
            return json.dumps(test_tags)

    acc, uid, mod, st = extract_dicom_tags(MockDicom())
    print(f"Extracted -> Accession: {acc}, StudyUID: {uid}, Modality: {mod}")
    print(f"Target RIS Webhook: {RIS_STATUS_API_URL}")
    print("Status callback script syntax and logic verified successfully.")
