#!/usr/bin/env python3
"""
Orthanc PACS Stable Study Callback Plugin
=========================================
Listens for Orthanc's 'OnStableStudy' event to detect when an entire DICOM imaging
study has finished transmitting across all series/slices.

Once marked 'Stable' by Orthanc (after no new instances have been received for
the configured StableAge timeout, typically 60 seconds), this plugin extracts
the Accession Number and Study Instance UID, and fires a single, clean HTTP POST
webhook to the .NET Core RIS API to transition the examination status to 'Completed'.

Architectural Benefits:
- Eliminates per-instance HTTP callbacks during large multi-frame CT/MRI series.
- Replaces in-memory Python debouncing arrays with Orthanc's native C++ event engine.
- Protects the RIS API and PostgreSQL database connection pools from exhaustion.
"""

import json
import logging
import os
import sys
from typing import Any, Dict, Optional, Tuple

import requests
from requests.exceptions import ConnectionError, RequestException, Timeout

# ==============================================================================
# Logging Configuration
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [STABLE_STUDY_CALLBACK] %(message)s"
)
logger = logging.getLogger("STABLE_STUDY_CALLBACK")

# ==============================================================================
# Orthanc Python SDK Import
# ==============================================================================
try:
    import orthanc
    HAS_ORTHANC = True
except ImportError:
    HAS_ORTHANC = False
    logger.warning(
        "Orthanc Python SDK ('orthanc') module not found in environment. "
        "Running in test/standalone mock mode."
    )

# ==============================================================================
# Environment Configuration & Service Endpoints
# ==============================================================================
# Default endpoint within Docker Compose network: http://ris-api:8080/api/exams/complete
# For standalone host testing, can override via RIS_COMPLETE_API_URL or RIS_API_URL env vars.
DEFAULT_RIS_URL = os.environ.get(
    "RIS_COMPLETE_API_URL",
    os.environ.get("RIS_STATUS_API_URL", "http://ris-api:8080/api/exams/complete")
)
if not DEFAULT_RIS_URL.endswith("/api/exams/complete"):
    DEFAULT_RIS_URL = DEFAULT_RIS_URL.rstrip("/") + "/api/exams/complete"

RIS_COMPLETE_API_URL = os.environ.get("RIS_COMPLETE_API_URL", DEFAULT_RIS_URL)
HTTP_TIMEOUT_SECONDS = float(os.environ.get("RIS_HTTP_TIMEOUT_SECONDS", "10.0"))


# ==============================================================================
# Metadata Extraction Helper
# ==============================================================================
def extract_study_identifiers(study_dict: Dict[str, Any]) -> Tuple[str, str]:
    """
    Extracts AccessionNumber and StudyInstanceUID from Orthanc's /studies/{id} JSON response.
    Gracefully handles empty, missing, or alternate hexadecimal DICOM tag keys.
    """
    main_tags = study_dict.get("MainDicomTags", {})

    # 1. Extract Accession Number (DICOM Tag 0008,0050)
    accession = (
        main_tags.get("AccessionNumber")
        or main_tags.get("0008,0050")
        or main_tags.get("00080050")
        or ""
    )
    if isinstance(accession, dict) and "Value" in accession:
        accession = accession["Value"]
    clean_accession = str(accession).strip() if accession is not None else ""

    # 2. Extract Study Instance UID (DICOM Tag 0020,000d)
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


# ==============================================================================
# Stable Study Callback
# ==============================================================================
def StableStudyCallback(studyId: str) -> None:
    """
    Callback function invoked by Orthanc when a study becomes 'Stable'.
    
    Args:
        studyId: Orthanc's internal 36-character hexadecimal UUID for the study.
    """
    logger.info(f"Orthanc detected Stable Study event for internal StudyID: '{studyId}'")

    if not HAS_ORTHANC:
        logger.warning(f"Orthanc SDK not available; skipping REST API fetch for StudyID '{studyId}'.")
        return

    # 1. Retrieve study details from Orthanc's internal REST API
    try:
        raw_response = orthanc.RestApiGet(f"/studies/{studyId}")
        if isinstance(raw_response, bytes):
            raw_response = raw_response.decode("utf-8")

        study_metadata = json.loads(raw_response) if isinstance(raw_response, str) else raw_response
        if not isinstance(study_metadata, dict):
            logger.error(f"Unexpected non-dict response format from /studies/{studyId}: {type(study_metadata)}")
            return

    except Exception as ex:
        # Wrap all Orthanc REST calls so failures never disrupt Orthanc core operations
        logger.error(f"Failed to retrieve metadata from Orthanc REST API for study '{studyId}': {ex}")
        return

    # 2. Extract Accession Number and Study Instance UID
    accession_number, study_instance_uid = extract_study_identifiers(study_metadata)

    logger.info(
        f"Study '{studyId}' resolved: AccessionNumber='{accession_number}', "
        f"StudyInstanceUID='{study_instance_uid}'"
    )

    if not accession_number and not study_instance_uid:
        logger.warning(
            f"Study '{studyId}' contains neither AccessionNumber nor StudyInstanceUID. "
            "Skipping RIS completion notification."
        )
        return

    # 3. Construct strictly formatted JSON payload
    payload = {
        "accessionNumber": accession_number,
        "studyInstanceUid": study_instance_uid
    }

    # 4. Dispatch single HTTP POST request to .NET Core RIS API
    logger.info(
        f"Sending exam completion webhook to RIS API at '{RIS_COMPLETE_API_URL}' "
        f"with payload: {payload}"
    )

    try:
        response = requests.post(
            RIS_COMPLETE_API_URL,
            json=payload,
            timeout=HTTP_TIMEOUT_SECONDS,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Orthanc-StableStudy-Plugin/1.0"
            }
        )

        if response.status_code in (200, 204):
            logger.info(
                f"RIS API successfully acknowledged exam completion (HTTP {response.status_code}): "
                f"{response.text}"
            )
        elif response.status_code == 404:
            logger.warning(
                f"RIS API reported exam not found for Accession='{accession_number}', "
                f"StudyUID='{study_instance_uid}' (HTTP 404): {response.text}"
            )
        else:
            logger.error(
                f"RIS API returned unexpected HTTP {response.status_code} for study '{studyId}': "
                f"{response.text[:300]}"
            )

    except Timeout:
        logger.error(
            f"Timeout ({HTTP_TIMEOUT_SECONDS}s) connecting to RIS API endpoint '{RIS_COMPLETE_API_URL}' "
            f"for study '{studyId}'."
        )
    except ConnectionError as ce:
        logger.error(
            f"Network connection failed while reaching RIS API at '{RIS_COMPLETE_API_URL}': {ce}"
        )
    except RequestException as re:
        logger.error(
            f"HTTP request error during RIS completion webhook for study '{studyId}': {re}"
        )
    except Exception as ex:
        # Guarantee that no unhandled exception escapes back to Orthanc's C++ core
        logger.error(
            f"Unexpected exception while sending completion notification for study '{studyId}': {ex}"
        )


# ==============================================================================
# Plugin Registration
# ==============================================================================
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
        orthanc.RegisterOnStableStudyCallback(StableStudyCallback)
        logger.info(
            "Successfully registered 'StableStudyCallback' with Orthanc via "
            "orthanc.RegisterOnStableStudyCallback()."
        )
    except Exception as err:
        logger.critical(f"Failed to register OnStableStudy callback with Orthanc: {err}")
else:
    logger.info("Plugin loaded in standalone context. Registration deferred to Orthanc startup.")


# ==============================================================================
# Local Self-Test & Diagnostic Entrypoint
# ==============================================================================
if __name__ == "__main__":
    print("=" * 70)
    print("Orthanc Stable Study Callback Plugin - Diagnostic Test")
    print("=" * 70)
    print(f"Target RIS Complete API Endpoint: {RIS_COMPLETE_API_URL}")
    print(f"HTTP Timeout:                     {HTTP_TIMEOUT_SECONDS} seconds")

    # Mock test payload matching Orthanc /studies/{id} REST format
    mock_study_json = {
        "ID": "6a735e5d-16a7f23c-73c3866f-4cb1c26b-16781fb4",
        "IsStable": True,
        "MainDicomTags": {
            "AccessionNumber": "ACC2026102201",
            "StudyInstanceUID": "2.25.13847291048291048102948192039102",
            "StudyDate": "20261022",
            "StudyDescription": "CT Chest with IV Contrast"
        }
    }

    acc, uid = extract_study_identifiers(mock_study_json)
    print("\n[Self-Test] Metadata Extraction:")
    print(f"  Extracted Accession Number: '{acc}'")
    print(f"  Extracted StudyInstanceUID: '{uid}'")

    test_payload = {
        "accessionNumber": acc,
        "studyInstanceUid": uid
    }
    print(f"  Constructed Webhook Payload: {json.dumps(test_payload)}")
    assert acc == "ACC2026102201", "Accession number mismatch!"
    assert uid == "2.25.13847291048291048102948192039102", "StudyInstanceUID mismatch!"
    print("\n✓ Self-test assertion passed successfully!")
    print("=" * 70)
