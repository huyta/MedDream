#!/usr/bin/env bash
set -euo pipefail

# Configuration
ORTHANC_HOST="${ORTHANC_HOST:-localhost}"
ORTHANC_PORT="${ORTHANC_HTTP_PORT:-8042}"
ORTHANC_USER="${ORTHANC_USER:-orthanc}"
ORTHANC_PASS="${ORTHANC_PASSWORD:-orthanc}"
MEDDREAM_PORT="${MEDDREAM_PORT:-8080}"

ORTHANC_URL="http://${ORTHANC_HOST}:${ORTHANC_PORT}"
AUTH_HEADER="-u ${ORTHANC_USER}:${ORTHANC_PASS}"

echo "=========================================="
echo " MedDream & Orthanc DICOM Import Tool"
echo "=========================================="

# Check if Orthanc is responding
echo "[1/4] Checking Orthanc PACS connection at ${ORTHANC_URL}..."
if ! curl -s -f ${AUTH_HEADER} "${ORTHANC_URL}/system" > /dev/null; then
    echo "Error: Cannot connect to Orthanc at ${ORTHANC_URL}."
    echo "Make sure containers are up and healthy: docker compose ps"
    exit 1
fi
echo "✓ Orthanc is healthy."

# Determine file source
DICOM_INPUT="${1:-}"
TEMP_DIR=""

if [ -z "${DICOM_INPUT}" ]; then
    echo "[2/4] No file provided. Downloading standard CT DICOM sample..."
    TEMP_DIR=$(mktemp -d)
    SAMPLE_FILE="${TEMP_DIR}/sample_ct.dcm"
    
    # Download standard DICOM sample from Cornerstone repository
    curl -sSL "https://raw.githubusercontent.com/cornerstonejs/cornerstoneWADOImageLoader/master/testImages/CT2_J2KR" -o "${SAMPLE_FILE}"
    
    TARGET_FILES=("${SAMPLE_FILE}")
else
    echo "[2/4] Processing provided path: ${DICOM_INPUT}"
    if [ -f "${DICOM_INPUT}" ]; then
        TARGET_FILES=("${DICOM_INPUT}")
    elif [ -d "${DICOM_INPUT}" ]; then
        TARGET_FILES=($(find "${DICOM_INPUT}" -type f \( -name "*.dcm" -o -name "*.DCM" -o ! -name "*.*" \)))
    else
        echo "Error: Path does not exist: ${DICOM_INPUT}"
        exit 1
    fi
fi

# Upload files to Orthanc
echo "[3/4] Uploading DICOM file(s) to Orthanc..."
LAST_PARENT_STUDY=""

for file in "${TARGET_FILES[@]}"; do
    if [ ! -s "${file}" ]; then
        continue
    fi
    echo "  -> Uploading: $(basename "${file}")"
    RESPONSE=$(curl -s -f ${AUTH_HEADER} -X POST "${ORTHANC_URL}/instances" --data-binary @"${file}" || true)
    if [ -z "${RESPONSE}" ]; then
        continue
    fi
    PARENT_STUDY=$(echo "${RESPONSE}" | grep -o '"ParentStudy"[^,]*' | cut -d'"' -f4 || true)
    if [ -n "${PARENT_STUDY}" ]; then
        LAST_PARENT_STUDY="${PARENT_STUDY}"
    fi
done

# Clean up temp files if created
if [ -n "${TEMP_DIR}" ] && [ -d "${TEMP_DIR}" ]; then
    rm -rf "${TEMP_DIR}"
fi

# Retrieve Study Information
echo "[4/4] Retrieving Study details..."
if [ -n "${LAST_PARENT_STUDY}" ]; then
    STUDY_INFO=$(curl -s -f ${AUTH_HEADER} "${ORTHANC_URL}/studies/${LAST_PARENT_STUDY}")
    STUDY_UID=$(echo "${STUDY_INFO}" | grep -o '"StudyInstanceUID"[^,]*' | cut -d'"' -f4 || true)
    PATIENT_ID=$(echo "${STUDY_INFO}" | grep -o '"PatientID"[^,]*' | cut -d'"' -f4 || true)
    PATIENT_NAME=$(echo "${STUDY_INFO}" | grep -o '"PatientName"[^,]*' | cut -d'"' -f4 || true)
    
    echo "=========================================="
    echo "✓ DICOM Study successfully uploaded!"
    echo "=========================================="
    echo "Patient ID:         ${PATIENT_ID:-N/A}"
    echo "Patient Name:       ${PATIENT_NAME:-N/A}"
    echo "Orthanc Study ID:   ${LAST_PARENT_STUDY}"
    echo "Study Instance UID: ${STUDY_UID}"
    echo "------------------------------------------"
    echo "MedDream Viewer URL:"
    echo "http://localhost:${MEDDREAM_PORT}/?study=${STUDY_UID}"
    echo "=========================================="
else
    echo "Uploaded, but could not determine Study ID. Check Orthanc Explorer at http://localhost:${ORTHANC_PORT}/app/explorer.html"
fi
