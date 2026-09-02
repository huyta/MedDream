#!/usr/bin/env python3
"""
DICOM Modality Worklist (MWL) Generator
=======================================
Creates standard-compliant DICOM Modality Worklist files (.wl / .dcm)
for use with PACS / Worklist servers (Orthanc Worklists plugin, DCMTK wlmscpfs, etc.)
and medical imaging modalities (CT, MR, US, CR, DX, XA, etc.).

Dependencies:
    pip install pydicom

Usage examples:
    # 1. Create a quick sample MWL file:
    python create_mwl.py sample

    # 2. Create a custom MWL file via CLI:
    python create_mwl.py create \
        --patient-id "PAT10045" \
        --patient-name "Doe^John" \
        --patient-sex "M" \
        --patient-dob "1985-06-20" \
        --accession "ACC20260901" \
        --modality "CT" \
        --station-ae "CT_SCANNER_1" \
        --procedure-desc "CT Chest with IV Contrast" \
        --start-time "2026-09-02 09:30:00" \
        --output "./worklists/pat10045_ct.wl"

    # 3. Create batch MWL files from JSON:
    python create_mwl.py batch --input sample_worklists.json --out-dir ./worklists

    # 4. Inspect / dump an existing .wl file:
    python create_mwl.py inspect --file ./worklists/pat10045_ct.wl
"""

import sys
import os
import json
import argparse
from datetime import datetime, date, time
from typing import Optional, Dict, Any, List

try:
    import pydicom
    from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
    from pydicom.sequence import Sequence
    from pydicom.uid import (
        ExplicitVRLittleEndian,
        generate_uid,
        PYDICOM_IMPLEMENTATION_UID,
    )
except ImportError:
    print(
        "Error: 'pydicom' is required to run this script.\n"
        "Install it via: pip install pydicom  OR  uv run --with pydicom python create_mwl.py",
        file=sys.stderr,
    )
    sys.exit(1)

# SOP Class UID for Modality Worklist Information Model - FIND
MODALITY_WORKLIST_FIND_SOP_CLASS_UID = "1.2.840.10008.5.1.4.31"


def format_dicom_date(dt: Optional[Any]) -> str:
    """Format date into DICOM DA format (YYYYMMDD)."""
    if dt is None:
        return datetime.now().strftime("%Y%m%d")
    if isinstance(dt, (datetime, date)):
        return dt.strftime("%Y%m%d")
    if isinstance(dt, str):
        cleaned = dt.replace("-", "").replace("/", "").strip()
        if len(cleaned) == 8 and cleaned.isdigit():
            return cleaned
        try:
            parsed = datetime.fromisoformat(dt)
            return parsed.strftime("%Y%m%d")
        except ValueError:
            pass
    return str(dt)


def format_dicom_time(tm: Optional[Any]) -> str:
    """Format time into DICOM TM format (HHMMSS)."""
    if tm is None:
        return datetime.now().strftime("%H%M%S")
    if isinstance(tm, (datetime, time)):
        return tm.strftime("%H%M%S")
    if isinstance(tm, str):
        cleaned = tm.replace(":", "").strip()
        if len(cleaned) in (4, 6) and cleaned.isdigit():
            return cleaned.ljust(6, "0")
        try:
            parsed = datetime.fromisoformat(tm)
            return parsed.strftime("%H%M%S")
        except ValueError:
            pass
    return str(tm)


def truncate_sh(val: Optional[str], max_len: int = 16) -> Optional[str]:
    """Ensure Short String (VR SH) attributes do not exceed DICOM maximum length (16 chars)."""
    if val is None:
        return None
    s = str(val).strip()
    return s[:max_len]


def create_mwl_dataset(
    # Patient Demographics
    patient_id: str,
    patient_name: str,
    patient_birth_date: Optional[str] = None,
    patient_sex: str = "O",
    patient_weight: Optional[float] = None,
    patient_size: Optional[float] = None,
    medical_alerts: Optional[str] = None,
    allergies: Optional[str] = None,
    pregnancy_status: Optional[int] = None,
    # Visit / Institution
    institution_name: str = "Hospital Medical Center",
    institution_address: Optional[str] = None,
    referring_physician: Optional[str] = None,
    admission_id: Optional[str] = None,
    # Requested Procedure
    accession_number: Optional[str] = None,
    study_instance_uid: Optional[str] = None,
    requested_procedure_id: Optional[str] = None,
    requested_procedure_desc: Optional[str] = None,
    requested_procedure_priority: str = "ROUTINE",
    requested_procedure_comments: Optional[str] = None,
    reason_for_procedure: Optional[str] = None,
    procedure_code: Optional[str] = None,
    procedure_code_meaning: Optional[str] = None,
    procedure_code_scheme: str = "99LOCAL",
    # Scheduled Procedure Step
    modality: str = "CT",
    station_ae_title: str = "MODALITY_AE",
    station_name: Optional[str] = None,
    scheduled_start_date: Optional[str] = None,
    scheduled_start_time: Optional[str] = None,
    scheduled_sps_id: Optional[str] = None,
    scheduled_sps_desc: Optional[str] = None,
    scheduled_sps_location: Optional[str] = None,
    scheduled_performing_physician: Optional[str] = None,
    scheduled_status: str = "SCHEDULED",
    protocol_code: Optional[str] = None,
    protocol_code_meaning: Optional[str] = None,
    protocol_code_scheme: str = "99LOCAL",
    # Specific Character Set
    character_set: str = "ISO_IR 192",  # UTF-8
) -> FileDataset:
    """
    Constructs a complete DICOM FileDataset representing a Modality Worklist (MWL) item.
    Conforms to DICOM PS 3.3 / PS 3.4 standard for Modality Worklist Information Model.
    """
    now = datetime.now()

    # Defaults for identifiers (fit within 16-char DICOM SH constraint)
    if not study_instance_uid:
        study_instance_uid = generate_uid()
    if not accession_number:
        accession_number = f"ACC{now.strftime('%y%m%d%H%M%S')}"
    if not requested_procedure_id:
        requested_procedure_id = f"RP{now.strftime('%y%m%d%H%M%S')}"
    if not scheduled_sps_id:
        scheduled_sps_id = f"SPS{now.strftime('%y%m%d%H%M%S')}"
    if not scheduled_sps_desc:
        scheduled_sps_desc = requested_procedure_desc or f"{modality} Examination"
    if not requested_procedure_desc:
        requested_procedure_desc = scheduled_sps_desc

    sop_instance_uid = generate_uid()

    # 1. Initialize File Meta Information (Group 0002)
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = MODALITY_WORKLIST_FIND_SOP_CLASS_UID
    file_meta.MediaStorageSOPInstanceUID = sop_instance_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
    file_meta.ImplementationVersionName = "MEDDREAM_MWL_1.0"

    # 2. Main FileDataset
    ds = FileDataset("", {}, file_meta=file_meta, preamble=b"\0" * 128)

    # SOP Common Module
    ds.SpecificCharacterSet = character_set
    ds.SOPClassUID = MODALITY_WORKLIST_FIND_SOP_CLASS_UID
    ds.SOPInstanceUID = sop_instance_uid
    ds.InstanceCreationDate = now.strftime("%Y%m%d")
    ds.InstanceCreationTime = now.strftime("%H%M%S")

    # Patient Identification & Demographics Module
    ds.PatientName = patient_name
    ds.PatientID = str(patient_id)
    if patient_birth_date:
        ds.PatientBirthDate = format_dicom_date(patient_birth_date)
    else:
        ds.PatientBirthDate = ""
    ds.PatientSex = patient_sex.upper() if patient_sex else "O"

    if patient_weight is not None:
        ds.PatientWeight = float(patient_weight)
    if patient_size is not None:
        ds.PatientSize = float(patient_size)
    if medical_alerts:
        ds.MedicalAlerts = medical_alerts
    if allergies:
        ds.Allergies = allergies
    if pregnancy_status is not None:
        ds.PregnancyStatus = int(pregnancy_status)

    # Visit / Institution Module
    ds.InstitutionName = institution_name
    if institution_address:
        ds.InstitutionAddress = institution_address
    if referring_physician:
        ds.ReferringPhysicianName = referring_physician
    else:
        ds.ReferringPhysicianName = ""
    if admission_id:
        ds.AdmissionID = truncate_sh(admission_id)

    # Requested Procedure Module
    ds.StudyInstanceUID = study_instance_uid
    ds.AccessionNumber = truncate_sh(accession_number)
    ds.RequestedProcedureID = truncate_sh(requested_procedure_id)
    ds.RequestedProcedureDescription = requested_procedure_desc
    ds.RequestedProcedurePriority = requested_procedure_priority
    if reason_for_procedure:
        ds.ReasonForTheRequestedProcedure = reason_for_procedure
    if requested_procedure_comments:
        ds.RequestedProcedureComments = requested_procedure_comments

    # Requested Procedure Code Sequence (Optional Code Sequence)
    if procedure_code and procedure_code_meaning:
        proc_code_item = Dataset()
        proc_code_item.CodeValue = str(procedure_code)
        proc_code_item.CodingSchemeDesignator = procedure_code_scheme
        proc_code_item.CodeMeaning = procedure_code_meaning
        ds.RequestedProcedureCodeSequence = Sequence([proc_code_item])

    # Scheduled Procedure Step (SPS) Sequence (0040,0100) - Core Worklist Sequence
    sps_item = Dataset()
    sps_item.ScheduledStationAETitle = station_ae_title
    if station_name:
        sps_item.ScheduledStationName = truncate_sh(station_name)
    sps_item.ScheduledProcedureStepStartDate = format_dicom_date(scheduled_start_date)
    sps_item.ScheduledProcedureStepStartTime = format_dicom_time(scheduled_start_time)
    sps_item.Modality = modality.upper()
    if scheduled_performing_physician:
        sps_item.ScheduledPerformingPhysicianName = scheduled_performing_physician
    else:
        sps_item.ScheduledPerformingPhysicianName = ""
    sps_item.ScheduledProcedureStepDescription = scheduled_sps_desc
    sps_item.ScheduledProcedureStepID = truncate_sh(scheduled_sps_id)
    if scheduled_sps_location:
        sps_item.ScheduledProcedureStepLocation = truncate_sh(scheduled_sps_location)
    sps_item.ScheduledProcedureStepStatus = scheduled_status

    # Scheduled Protocol Code Sequence (Optional inside SPS)
    if protocol_code and protocol_code_meaning:
        protocol_code_item = Dataset()
        protocol_code_item.CodeValue = str(protocol_code)
        protocol_code_item.CodingSchemeDesignator = protocol_code_scheme
        protocol_code_item.CodeMeaning = protocol_code_meaning
        sps_item.ScheduledProtocolCodeSequence = Sequence([protocol_code_item])

    ds.ScheduledProcedureStepSequence = Sequence([sps_item])

    # Set encoding details
    ds.is_little_endian = True
    ds.is_implicit_VR = False

    return ds


def save_mwl_file(
    dataset: FileDataset, output_path: str, format_type: str = "dicom"
) -> str:
    """
    Saves a DICOM MWL dataset to disk as a binary .wl/.dcm file or DCMTK .dump format.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    if format_type.lower() in ("dump", "dcmtk_dump"):
        # Text dump format suitable for DCMTK dump2dcm
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"# DICOM Modality Worklist Dump\n")
            f.write(f"# Generated by MedDream MWL Generator\n")
            f.write(str(dataset))
        return output_path
    else:
        # Standard binary DICOM file (.wl / .dcm)
        dataset.save_as(output_path, write_like_original=False)
        return output_path


def inspect_mwl_file(file_path: str) -> None:
    """
    Reads and nicely formats all DICOM attributes from an existing .wl or .dcm file.
    """
    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        return

    try:
        ds = pydicom.dcmread(file_path, force=True)
    except Exception as e:
        print(f"Error reading DICOM file '{file_path}': {e}", file=sys.stderr)
        return

    print("=" * 80)
    print(f"DICOM Modality Worklist Inspector: {os.path.basename(file_path)}")
    print("=" * 80)
    print(f"File Path: {os.path.abspath(file_path)}")
    print(f"SOP Class UID: {getattr(ds, 'SOPClassUID', 'N/A')}")
    print(f"SOP Instance UID: {getattr(ds, 'SOPInstanceUID', 'N/A')}")
    print("-" * 80)
    print(f"Patient Name:       {getattr(ds, 'PatientName', 'N/A')}")
    print(f"Patient ID:         {getattr(ds, 'PatientID', 'N/A')}")
    print(f"Birth Date:         {getattr(ds, 'PatientBirthDate', 'N/A')}")
    print(f"Sex:                {getattr(ds, 'PatientSex', 'N/A')}")
    print(f"Accession Number:   {getattr(ds, 'AccessionNumber', 'N/A')}")
    print(f"Study Instance UID: {getattr(ds, 'StudyInstanceUID', 'N/A')}")
    print(f"Requested Proc ID:  {getattr(ds, 'RequestedProcedureID', 'N/A')}")
    print(f"Requested Proc Desc:{getattr(ds, 'RequestedProcedureDescription', 'N/A')}")
    print(f"Priority:           {getattr(ds, 'RequestedProcedurePriority', 'N/A')}")
    print(f"Institution:        {getattr(ds, 'InstitutionName', 'N/A')}")
    print(f"Referring Physician:{getattr(ds, 'ReferringPhysicianName', 'N/A')}")

    if hasattr(ds, "ScheduledProcedureStepSequence") and len(
        ds.ScheduledProcedureStepSequence
    ) > 0:
        print("-" * 80)
        print("Scheduled Procedure Step Sequence (0040,0100):")
        for idx, sps in enumerate(ds.ScheduledProcedureStepSequence, start=1):
            print(f"  Step #{idx}:")
            print(f"    Modality:             {getattr(sps, 'Modality', 'N/A')}")
            print(f"    Station AE Title:     {getattr(sps, 'ScheduledStationAETitle', 'N/A')}")
            print(f"    Station Name:         {getattr(sps, 'ScheduledStationName', 'N/A')}")
            print(f"    Scheduled Date:       {getattr(sps, 'ScheduledProcedureStepStartDate', 'N/A')}")
            print(f"    Scheduled Time:       {getattr(sps, 'ScheduledProcedureStepStartTime', 'N/A')}")
            print(f"    Step Description:     {getattr(sps, 'ScheduledProcedureStepDescription', 'N/A')}")
            print(f"    Step ID:              {getattr(sps, 'ScheduledProcedureStepID', 'N/A')}")
            print(f"    Performing Physician: {getattr(sps, 'ScheduledPerformingPhysicianName', 'N/A')}")
            print(f"    Status:               {getattr(sps, 'ScheduledProcedureStepStatus', 'N/A')}")
    print("=" * 80)


def create_sample_worklists(output_dir: str = "./worklists") -> List[str]:
    """Generates a collection of realistic test worklist items across multiple modalities."""
    today = datetime.now()
    date_str = today.strftime("%Y%m%d")

    samples = [
        {
            "filename": "sample_ct_chest.wl",
            "patient_id": "P1001",
            "patient_name": "Smith^John^A",
            "patient_birth_date": "19780312",
            "patient_sex": "M",
            "patient_weight": 82.5,
            "patient_size": 1.80,
            "accession_number": f"ACC{date_str}001",
            "institution_name": "General Medical Center",
            "referring_physician": "Dr^Adams^Sarah",
            "requested_procedure_id": "RP-CT-001",
            "requested_procedure_desc": "CT Chest with IV Contrast",
            "requested_procedure_priority": "ROUTINE",
            "reason_for_procedure": "Chronic cough, rule out pulmonary embolism",
            "modality": "CT",
            "station_ae_title": "CT_SCANNER_1",
            "station_name": "CT Room 101",
            "scheduled_start_date": date_str,
            "scheduled_start_time": "090000",
            "scheduled_sps_id": "SPS-CT-001",
            "scheduled_sps_desc": "CT Chest Angiography",
            "scheduled_performing_physician": "Dr^Taylor^Mark",
        },
        {
            "filename": "sample_mr_brain.wl",
            "patient_id": "P1002",
            "patient_name": "Johnson^Emily^R",
            "patient_birth_date": "19901105",
            "patient_sex": "F",
            "patient_weight": 61.0,
            "patient_size": 1.65,
            "allergies": "Penicillin",
            "accession_number": f"ACC{date_str}002",
            "institution_name": "General Medical Center",
            "referring_physician": "Dr^House^Gregory",
            "requested_procedure_id": "RP-MR-002",
            "requested_procedure_desc": "MRI Brain with & without Contrast",
            "requested_procedure_priority": "STAT",
            "reason_for_procedure": "Severe migraine and visual aura",
            "modality": "MR",
            "station_ae_title": "MR_SCANNER_3T",
            "station_name": "MRI Suite 2",
            "scheduled_start_date": date_str,
            "scheduled_start_time": "103000",
            "scheduled_sps_id": "SPS-MR-002",
            "scheduled_sps_desc": "MRI Head Protocol",
            "scheduled_performing_physician": "Dr^Wilson^James",
        },
        {
            "filename": "sample_us_abdomen.wl",
            "patient_id": "P1003",
            "patient_name": "Brown^Michael^K",
            "patient_birth_date": "19650722",
            "patient_sex": "M",
            "patient_weight": 76.0,
            "accession_number": f"ACC{date_str}003",
            "institution_name": "General Medical Center",
            "referring_physician": "Dr^Cuddy^Lisa",
            "requested_procedure_id": "RP-US-003",
            "requested_procedure_desc": "Ultrasound Abdomen Complete",
            "requested_procedure_priority": "ROUTINE",
            "reason_for_procedure": "Right upper quadrant pain",
            "modality": "US",
            "station_ae_title": "US_ROOM_A",
            "station_name": "US Room A",
            "scheduled_start_date": date_str,
            "scheduled_start_time": "111500",
            "scheduled_sps_id": "SPS-US-003",
            "scheduled_sps_desc": "US Upper Abdomen",
            "scheduled_performing_physician": "Dr^Foreman^Eric",
        },
        {
            "filename": "sample_dx_chest.wl",
            "patient_id": "P1004",
            "patient_name": "Garcia^Maria^L",
            "patient_birth_date": "19830418",
            "patient_sex": "F",
            "patient_weight": 58.0,
            "accession_number": f"ACC{date_str}004",
            "institution_name": "General Medical Center",
            "referring_physician": "Dr^Cameron^Allison",
            "requested_procedure_id": "RP-DX-004",
            "requested_procedure_desc": "X-Ray Chest 2 Views (PA & Lateral)",
            "requested_procedure_priority": "HIGH",
            "reason_for_procedure": "Pre-operative evaluation",
            "modality": "DX",
            "station_ae_title": "XRAY_ROOM_1",
            "station_name": "X-Ray Room 1",
            "scheduled_start_date": date_str,
            "scheduled_start_time": "130000",
            "scheduled_sps_id": "SPS-DX-004",
            "scheduled_sps_desc": "Chest PA + LAT",
            "scheduled_performing_physician": "Dr^Chase^Robert",
        },
    ]

    created_paths = []
    for item in samples:
        filename = item.pop("filename")
        out_path = os.path.join(output_dir, filename)
        ds = create_mwl_dataset(**item)
        saved = save_mwl_file(ds, out_path)
        created_paths.append(saved)
        print(f"✓ Created sample MWL: {saved} ({item['modality']} - {item['patient_name']})")

    return created_paths


def process_batch_json(json_path: str, output_dir: str) -> List[str]:
    """Reads a JSON file containing a list of MWL item definitions and generates .wl files."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "worklists" in data:
        items = data["worklists"]
    elif isinstance(data, list):
        items = data
    else:
        items = [data]

    created = []
    for idx, item_data in enumerate(items, start=1):
        filename = item_data.pop(
            "filename",
            f"mwl_{item_data.get('patient_id', idx)}_{item_data.get('modality', 'MOD')}.wl",
        )
        out_path = os.path.join(output_dir, filename)
        ds = create_mwl_dataset(**item_data)
        saved = save_mwl_file(ds, out_path)
        created.append(saved)
        print(f"✓ [{idx}/{len(items)}] Created MWL: {saved}")

    return created


def parse_args():
    parser = argparse.ArgumentParser(
        description="DICOM Modality Worklist (MWL) File Generator for Orthanc, PACS & Modalities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Command: create
    create_parser = subparsers.add_parser("create", help="Create a single MWL (.wl) file")
    # Patient Demographics
    create_parser.add_argument(
        "--patient-id", required=True, help="Patient ID / Medical Record Number"
    )
    create_parser.add_argument(
        "--patient-name",
        required=True,
        help="Patient Name in DICOM format (e.g. 'Last^First^Middle' or 'Doe^John')",
    )
    create_parser.add_argument(
        "--patient-dob", help="Patient Date of Birth (YYYYMMDD or YYYY-MM-DD)"
    )
    create_parser.add_argument(
        "--patient-sex",
        choices=["M", "F", "O", "m", "f", "o"],
        default="O",
        help="Patient Sex (M/F/O)",
    )
    create_parser.add_argument(
        "--patient-weight", type=float, help="Patient Weight in kg (e.g. 70.5)"
    )
    create_parser.add_argument(
        "--patient-size", type=float, help="Patient Height/Size in meters (e.g. 1.75)"
    )
    create_parser.add_argument("--allergies", help="Known patient allergies")
    create_parser.add_argument("--medical-alerts", help="Medical alerts")

    # Procedure / Order
    create_parser.add_argument(
        "--accession", help="Accession Number (defaults to autogenerated timestamp)"
    )
    create_parser.add_argument("--study-uid", help="Study Instance UID (auto-generated if omitted)")
    create_parser.add_argument(
        "--procedure-id", help="Requested Procedure ID (e.g. RP1001)"
    )
    create_parser.add_argument(
        "--procedure-desc", help="Requested Procedure Description (e.g. 'CT Chest with Contrast')"
    )
    create_parser.add_argument(
        "--priority",
        choices=["STAT", "HIGH", "ROUTINE", "MEDIUM", "LOW"],
        default="ROUTINE",
        help="Procedure Priority",
    )
    create_parser.add_argument(
        "--reason", help="Clinical reason for requested procedure"
    )
    create_parser.add_argument(
        "--referring-dr", help="Referring Physician Name (e.g. 'House^Gregory^Dr')"
    )
    create_parser.add_argument(
        "--institution",
        default="Hospital Medical Center",
        help="Institution / Hospital Name",
    )

    # Scheduled Step
    create_parser.add_argument(
        "--modality",
        default="CT",
        help="Modality code (CT, MR, US, DX, CR, XA, NM, PT, MG, etc.)",
    )
    create_parser.add_argument(
        "--station-ae",
        default="MODALITY_AE",
        help="Scheduled Station AE Title (e.g. CT_SCANNER_1)",
    )
    create_parser.add_argument("--station-name", help="Station Name (e.g. Room 101)")
    create_parser.add_argument(
        "--start-date",
        help="Scheduled Start Date (YYYYMMDD or YYYY-MM-DD, defaults to today)",
    )
    create_parser.add_argument(
        "--start-time",
        help="Scheduled Start Time (HHMMSS or HH:MM:SS, defaults to current time)",
    )
    create_parser.add_argument(
        "--performing-dr", help="Scheduled Performing Physician Name"
    )
    create_parser.add_argument(
        "--location", help="Scheduled Procedure Location / Room"
    )

    # Output options
    create_parser.add_argument(
        "-o",
        "--output",
        default="worklist.wl",
        help="Output file path (defaults to worklist.wl)",
    )
    create_parser.add_argument(
        "--format",
        choices=["dicom", "dump"],
        default="dicom",
        help="File format: 'dicom' (.wl binary) or 'dump' (DCMTK text dump)",
    )

    # Command: sample
    sample_parser = subparsers.add_parser(
        "sample", help="Generate ready-to-use sample MWL files (CT, MR, US, DX)"
    )
    sample_parser.add_argument(
        "-d",
        "--out-dir",
        default="./worklists",
        help="Output directory for sample files (default: ./worklists)",
    )

    # Command: batch
    batch_parser = subparsers.add_parser(
        "batch", help="Generate multiple MWL files from a JSON config file"
    )
    batch_parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Path to JSON file with worklist definitions",
    )
    batch_parser.add_argument(
        "-d",
        "--out-dir",
        default="./worklists",
        help="Output directory for generated .wl files (default: ./worklists)",
    )

    # Command: inspect
    inspect_parser = subparsers.add_parser(
        "inspect", help="Inspect and dump DICOM tags from an existing .wl / .dcm file"
    )
    inspect_parser.add_argument(
        "-f", "--file", required=True, help="Path to .wl or .dcm file to inspect"
    )

    return parser


def main():
    parser = parse_args()

    if len(sys.argv) == 1:
        # Default action when no arguments are provided: generate sample worklists and show help
        print("No command specified. Generating sample Modality Worklists in './worklists'...\n")
        created = create_sample_worklists("./worklists")
        print("\n" + "=" * 80)
        print("Sample worklist items generated successfully!")
        print("To inspect any file, run:")
        print(f"  python {sys.argv[0]} inspect --file {created[0]}")
        print("\nRun with --help for all available commands and options.")
        print("=" * 80)
        return

    args = parser.parse_args()

    if args.command == "create":
        ds = create_mwl_dataset(
            patient_id=args.patient_id,
            patient_name=args.patient_name,
            patient_birth_date=args.patient_dob,
            patient_sex=args.patient_sex,
            patient_weight=args.patient_weight,
            patient_size=args.patient_size,
            allergies=args.allergies,
            medical_alerts=args.medical_alerts,
            accession_number=args.accession,
            study_instance_uid=args.study_uid,
            requested_procedure_id=args.procedure_id,
            requested_procedure_desc=args.procedure_desc,
            requested_procedure_priority=args.priority,
            reason_for_procedure=args.reason,
            referring_physician=args.referring_dr,
            institution_name=args.institution,
            modality=args.modality,
            station_ae_title=args.station_ae,
            station_name=args.station_name,
            scheduled_start_date=args.start_date,
            scheduled_start_time=args.start_time,
            scheduled_sps_location=args.location,
            scheduled_performing_physician=args.performing_dr,
        )
        saved_path = save_mwl_file(ds, args.output, format_type=args.format)
        print(f"✓ Successfully generated MWL file: {saved_path}")
        print(f"  Patient: {args.patient_name} (ID: {args.patient_id})")
        print(f"  Modality: {args.modality} | Station AE: {args.station_ae}")
        print(f"  Accession: {ds.AccessionNumber}")

    elif args.command == "sample":
        create_sample_worklists(args.out_dir)

    elif args.command == "batch":
        process_batch_json(args.input, args.out_dir)

    elif args.command == "inspect":
        inspect_mwl_file(args.file)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
