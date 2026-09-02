"""
DICOM Modality Worklist (.wl) Generator Utility
===============================================
Generates fully-compliant DICOM Modality Worklist files for testing
and populating the MWL SCP storage repository.
"""

from datetime import datetime, date, time
from pathlib import Path
from typing import Optional, Dict, Any, List
import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import (
    ExplicitVRLittleEndian,
    generate_uid,
    PYDICOM_IMPLEMENTATION_UID,
)

MODALITY_WORKLIST_FIND_SOP_CLASS_UID = "1.2.840.10008.5.1.4.31"


def create_worklist_dataset(
    patient_id: str = "P1001",
    patient_name: str = "Smith^John^A",
    patient_sex: str = "M",
    patient_dob: str = "19800101",
    patient_weight: Optional[float] = 75.0,
    patient_size: Optional[float] = 1.75,
    accession_number: str = "ACC20260902001",
    study_instance_uid: Optional[str] = None,
    requested_procedure_id: str = "RP001",
    requested_procedure_desc: str = "Routine Scan",
    requested_procedure_priority: str = "ROUTINE",
    modality: str = "CT",
    scheduled_date: Optional[str] = None,
    scheduled_time: Optional[str] = None,
    scheduled_station_ae: str = "CT_SCANNER_1",
    scheduled_station_name: str = "Room 101",
    scheduled_physician: str = "Dr^Physician^A",
    scheduled_step_id: str = "SPS001",
    scheduled_step_desc: Optional[str] = None,
    referring_physician: str = "Dr^Referring^B",
    institution_name: str = "Hospital Medical Center",
    reason_for_procedure: str = "Diagnostic Evaluation",
) -> FileDataset:
    """Creates a complete DICOM FileDataset for Modality Worklist."""
    sop_instance_uid = generate_uid()
    study_uid = study_instance_uid or generate_uid()
    now = datetime.now()
    today_str = now.strftime("%Y%m%d")
    now_time_str = now.strftime("%H%M%S")

    sps_date = (scheduled_date or today_str).replace("-", "").replace("/", "")
    sps_time = (scheduled_time or "090000").replace(":", "")

    file_meta = FileMetaDataset()
    file_meta.FileMetaInformationGroupLength = 200
    file_meta.FileMetaInformationVersion = b"\x00\x01"
    file_meta.MediaStorageSOPClassUID = MODALITY_WORKLIST_FIND_SOP_CLASS_UID
    file_meta.MediaStorageSOPInstanceUID = sop_instance_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
    file_meta.ImplementationVersionName = "MEDDREAM_MWL"

    ds = FileDataset("", {}, file_meta=file_meta, preamble=b"\x00" * 128)

    # Top-Level Identification
    ds.SpecificCharacterSet = "ISO_IR 192"  # UTF-8
    ds.InstanceCreationDate = today_str
    ds.InstanceCreationTime = now_time_str
    ds.SOPClassUID = MODALITY_WORKLIST_FIND_SOP_CLASS_UID
    ds.SOPInstanceUID = sop_instance_uid
    ds.AccessionNumber = accession_number
    ds.InstitutionName = institution_name
    ds.ReferringPhysicianName = referring_physician

    # Patient Demographics
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.PatientBirthDate = patient_dob.replace("-", "").replace("/", "")
    ds.PatientSex = patient_sex
    if patient_size is not None:
        ds.PatientSize = str(patient_size)
    if patient_weight is not None:
        ds.PatientWeight = str(patient_weight)

    # Requested Procedure
    ds.StudyInstanceUID = study_uid
    ds.RequestedProcedureDescription = requested_procedure_desc
    ds.RequestedProcedureID = requested_procedure_id
    ds.ReasonForTheRequestedProcedure = reason_for_procedure
    ds.RequestedProcedurePriority = requested_procedure_priority

    # Scheduled Procedure Step Sequence (0040,0100)
    sps = Dataset()
    sps.Modality = modality
    sps.ScheduledStationAETitle = scheduled_station_ae
    sps.ScheduledProcedureStepStartDate = sps_date
    sps.ScheduledProcedureStepStartTime = sps_time
    sps.ScheduledPerformingPhysicianName = scheduled_physician
    sps.ScheduledProcedureStepDescription = scheduled_step_desc or requested_procedure_desc
    sps.ScheduledProcedureStepID = scheduled_step_id
    sps.ScheduledStationName = scheduled_station_name
    sps.ScheduledProcedureStepStatus = "SCHEDULED"

    ds.ScheduledProcedureStepSequence = Sequence([sps])
    return ds


def create_sample_worklist_files(output_dir: Path) -> List[Path]:
    """Generates a diverse set of realistic sample .wl worklist files."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")

    samples = [
        {
            "patient_id": "P1001",
            "patient_name": "Smith^John^A",
            "patient_sex": "M",
            "patient_dob": "19780312",
            "patient_weight": 82.5,
            "patient_size": 1.80,
            "accession_number": "ACC20260901001",
            "requested_procedure_id": "RP-CT-001",
            "requested_procedure_desc": "CT Chest with IV Contrast",
            "modality": "CT",
            "scheduled_date": today,
            "scheduled_time": "090000",
            "scheduled_station_ae": "CT_SCANNER_1",
            "scheduled_station_name": "CT Room 101",
            "scheduled_physician": "Dr^Taylor^Mark",
            "scheduled_step_id": "SPS-CT-001",
            "referring_physician": "Dr^Adams^Sarah",
            "institution_name": "General Medical Center",
            "filename": "sample_01_ct_chest.wl",
        },
        {
            "patient_id": "P1002",
            "patient_name": "Johnson^Emily^R",
            "patient_sex": "F",
            "patient_dob": "19901105",
            "patient_weight": 61.0,
            "patient_size": 1.65,
            "accession_number": "ACC20260901002",
            "requested_procedure_id": "RP-MR-002",
            "requested_procedure_desc": "MRI Brain with and without Contrast",
            "modality": "MR",
            "scheduled_date": today,
            "scheduled_time": "103000",
            "scheduled_station_ae": "MR_SCANNER_1",
            "scheduled_station_name": "MRI Suite 1",
            "scheduled_physician": "Dr^Taylor^Mark",
            "scheduled_step_id": "SPS-MR-002",
            "referring_physician": "Dr^Nguyen^David",
            "institution_name": "General Medical Center",
            "filename": "sample_02_mr_brain.wl",
        },
        {
            "patient_id": "P1003",
            "patient_name": "Williams^Robert^T",
            "patient_sex": "M",
            "patient_dob": "19650822",
            "patient_weight": 95.0,
            "patient_size": 1.78,
            "accession_number": "ACC20260901003",
            "requested_procedure_id": "RP-DX-003",
            "requested_procedure_desc": "Chest 2 Views PA and Lateral",
            "modality": "DX",
            "scheduled_date": today,
            "scheduled_time": "111500",
            "scheduled_station_ae": "XR_ROOM_2",
            "scheduled_station_name": "X-Ray Room 2",
            "scheduled_physician": "Dr^Miller^Jessica",
            "scheduled_step_id": "SPS-DX-003",
            "referring_physician": "Dr^Adams^Sarah",
            "institution_name": "General Medical Center",
            "filename": "sample_03_dx_chest.wl",
        },
        {
            "patient_id": "P1004",
            "patient_name": "Garcia^Maria^L",
            "patient_sex": "F",
            "patient_dob": "19830417",
            "patient_weight": 58.0,
            "patient_size": 1.60,
            "accession_number": "ACC20260901004",
            "requested_procedure_id": "RP-US-004",
            "requested_procedure_desc": "Ultrasound Abdomen Complete",
            "modality": "US",
            "scheduled_date": today,
            "scheduled_time": "130000",
            "scheduled_station_ae": "US_ROOM_1",
            "scheduled_station_name": "US Room 1",
            "scheduled_physician": "Dr^Miller^Jessica",
            "scheduled_step_id": "SPS-US-004",
            "referring_physician": "Dr^Nguyen^David",
            "institution_name": "General Medical Center",
            "filename": "sample_04_us_abdomen.wl",
        },
        {
            "patient_id": "P1005",
            "patient_name": "Curie^Marie",
            "patient_sex": "F",
            "patient_dob": "18671107",
            "patient_weight": 55.0,
            "patient_size": 1.58,
            "accession_number": "ACC20260901005",
            "requested_procedure_id": "RP-MR-005",
            "requested_procedure_desc": "MRI Spine Lumbar without Contrast",
            "modality": "MR",
            "scheduled_date": today,
            "scheduled_time": "143000",
            "scheduled_station_ae": "MR_SCANNER_1",
            "scheduled_station_name": "MRI Suite 1",
            "scheduled_physician": "Dr^Taylor^Mark",
            "scheduled_step_id": "SPS-MR-005",
            "referring_physician": "Dr^Adams^Sarah",
            "institution_name": "General Medical Center",
            "filename": "sample_05_mr_lumbar.wl",
        },
    ]

    created_paths = []
    for item in samples:
        fname = item.pop("filename")
        ds = create_worklist_dataset(**item)
        file_path = output_dir / fname
        pydicom.dcmwrite(file_path, ds, enforce_file_format=True)
        created_paths.append(file_path)

    return created_paths
