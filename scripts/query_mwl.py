#!/usr/bin/env python3
"""
DICOM Modality Worklist (MWL) Query Client (C-FIND SCU)
======================================================
Queries Orthanc (or any PACS / MWL SCP) using standard DICOM C-FIND DIMSE protocol
(SOP Class UID: 1.2.840.10008.5.1.4.31 - Modality Worklist Information Model - FIND).

Dependencies:
    pip install pydicom pynetdicom

Usage:
    # Query all worklist entries from Orthanc:
    python query_mwl.py

    # Query with specific filters:
    python query_mwl.py --patient-id P1001
    python query_mwl.py --modality CT
    python query_mwl.py --patient-name "Smith*"
    python query_mwl.py --host localhost --port 4242 --called-aet ORTHANC
"""

import sys
import argparse
from typing import Optional

try:
    import pydicom
    from pydicom.dataset import Dataset
    from pydicom.sequence import Sequence
    from pynetdicom import AE
    from pynetdicom.sop_class import (
        ModalityWorklistInformationFind,
        Verification,
    )
except ImportError:
    try:
        # Fallback for older pynetdicom versions
        import pydicom
        from pydicom.dataset import Dataset
        from pydicom.sequence import Sequence
        from pynetdicom import AE
        from pynetdicom.sop_class import (
            ModalityWorklistInformationModelFind as ModalityWorklistInformationFind,
            Verification,
        )
    except Exception as e:
        print(
            f"Error: 'pydicom' and 'pynetdicom' are required ({e}).\n"
            "Install via: pip install pydicom pynetdicom  OR  uv run --with pydicom --with pynetdicom python query_mwl.py",
            file=sys.stderr,
        )
        sys.exit(1)

MODALITY_WORKLIST_FIND_UID = "1.2.840.10008.5.1.4.31"


def create_mwl_query_dataset(
    patient_id: Optional[str] = None,
    patient_name: Optional[str] = None,
    modality: Optional[str] = None,
    scheduled_date: Optional[str] = None,
    station_ae: Optional[str] = None,
    accession_number: Optional[str] = None,
) -> Dataset:
    """
    Constructs the DICOM query dataset with return keys and optional filter keys
    for Modality Worklist C-FIND.
    """
    query = Dataset()

    # Patient Identification & Demographics Return Keys / Filters
    query.PatientName = patient_name or ""
    query.PatientID = patient_id or ""
    query.PatientBirthDate = ""
    query.PatientSex = ""
    query.PatientWeight = ""
    query.MedicalAlerts = ""
    query.Allergies = ""

    # Requested Procedure Return Keys / Filters
    query.StudyInstanceUID = ""
    query.AccessionNumber = accession_number or ""
    query.RequestedProcedureID = ""
    query.RequestedProcedureDescription = ""
    query.RequestedProcedurePriority = ""
    query.ReferringPhysicianName = ""
    query.InstitutionName = ""

    # Scheduled Procedure Step Sequence (0040,0100)
    sps_query = Dataset()
    sps_query.ScheduledStationAETitle = station_ae or ""
    sps_query.ScheduledStationName = ""
    sps_query.ScheduledProcedureStepStartDate = scheduled_date or ""
    sps_query.ScheduledProcedureStepStartTime = ""
    sps_query.Modality = modality or ""
    sps_query.ScheduledPerformingPhysicianName = ""
    sps_query.ScheduledProcedureStepDescription = ""
    sps_query.ScheduledProcedureStepID = ""
    sps_query.ScheduledProcedureStepLocation = ""
    sps_query.ScheduledProcedureStepStatus = ""

    query.ScheduledProcedureStepSequence = Sequence([sps_query])

    return query


def query_mwl_scp(
    host: str = "localhost",
    port: int = 4242,
    called_aet: str = "ORTHANC",
    calling_aet: str = "MWL_SCU",
    patient_id: Optional[str] = None,
    patient_name: Optional[str] = None,
    modality: Optional[str] = None,
    scheduled_date: Optional[str] = None,
    station_ae: Optional[str] = None,
    accession_number: Optional[str] = None,
) -> None:
    """
    Establishes a DICOM association with the SCP and sends C-FIND request.
    """
    ae = AE(ae_title=calling_aet)
    # Add Modality Worklist Presentation Context
    ae.add_requested_context(ModalityWorklistInformationFind)
    ae.add_requested_context(Verification)

    print("=" * 80)
    print(f"Connecting to DICOM Worklist Server: {called_aet}@{host}:{port}")
    print("=" * 80)

    # Establish Association
    assoc = ae.associate(host, port, ae_title=called_aet)
    if not assoc.is_established:
        print(f"❌ Failed to establish DICOM association with {called_aet}@{host}:{port}")
        return

    print("✓ DICOM Association established successfully!")

    # Build query dataset
    query_ds = create_mwl_query_dataset(
        patient_id=patient_id,
        patient_name=patient_name,
        modality=modality,
        scheduled_date=scheduled_date,
        station_ae=station_ae,
        accession_number=accession_number,
    )

    print(f"\nSending C-FIND Request (SOP Class: Modality Worklist Information Model - FIND)...")
    if patient_id:
        print(f"  Filter -> Patient ID: {patient_id}")
    if patient_name:
        print(f"  Filter -> Patient Name: {patient_name}")
    if modality:
        print(f"  Filter -> Modality: {modality}")
    if station_ae:
        print(f"  Filter -> Station AE: {station_ae}")
    if scheduled_date:
        print(f"  Filter -> Scheduled Date: {scheduled_date}")

    responses = assoc.send_c_find(query_ds, ModalityWorklistInformationFind)

    match_count = 0
    print("\n" + "-" * 80)
    print("MATCHING WORKLIST RESULTS:")
    print("-" * 80)

    for status, identifier in responses:
        if status:
            # Status 0xFF00 or 0xFF01 indicates Pending (a matching dataset was returned)
            if status.Status in (0xFF00, 0xFF01) and identifier is not None:
                match_count += 1
                p_name = getattr(identifier, "PatientName", "N/A")
                p_id = getattr(identifier, "PatientID", "N/A")
                p_dob = getattr(identifier, "PatientBirthDate", "N/A")
                p_sex = getattr(identifier, "PatientSex", "N/A")
                acc = getattr(identifier, "AccessionNumber", "N/A")
                study_uid = getattr(identifier, "StudyInstanceUID", "N/A")
                rp_desc = getattr(identifier, "RequestedProcedureDescription", "N/A")
                rp_prio = getattr(identifier, "RequestedProcedurePriority", "N/A")

                # Scheduled Step details
                sps_list = getattr(identifier, "ScheduledProcedureStepSequence", [])
                sps_info = []
                if sps_list:
                    for s in sps_list:
                        s_mod = getattr(s, "Modality", "N/A")
                        s_ae = getattr(s, "ScheduledStationAETitle", "N/A")
                        s_date = getattr(s, "ScheduledProcedureStepStartDate", "N/A")
                        s_time = getattr(s, "ScheduledProcedureStepStartTime", "N/A")
                        s_desc = getattr(s, "ScheduledProcedureStepDescription", "N/A")
                        sps_info.append(f"[{s_mod}] on '{s_ae}' at {s_date} {s_time} ({s_desc})")

                print(f"\n[Result #{match_count}]")
                print(f"  Patient:         {p_name} (ID: {p_id}, DOB: {p_dob}, Sex: {p_sex})")
                print(f"  Accession:       {acc}")
                print(f"  Procedure:       {rp_desc} [Priority: {rp_prio}]")
                print(f"  Study UID:       {study_uid}")
                if sps_info:
                    print(f"  Scheduled Steps: {', '.join(sps_info)}")
            elif status.Status == 0x0000:
                print(f"\n✓ C-FIND completed successfully (Status: 0x0000 Success).")
            else:
                pass
        else:
            print(f"Connection lost or communication error occurred.")

    assoc.release()
    print("-" * 80)
    print(f"Total matching MWL records found: {match_count}")
    print("=" * 80)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Query Orthanc / PACS Modality Worklist via DICOM C-FIND (MWL SCU)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default="localhost", help="PACS / Orthanc hostname or IP")
    parser.add_argument("--port", type=int, default=4242, help="DICOM DIMSE port")
    parser.add_argument("--called-aet", default="ORTHANC", help="Called AE Title of the PACS")
    parser.add_argument("--calling-aet", default="MWL_SCU", help="Calling AE Title of this client")
    parser.add_argument("--patient-id", help="Filter by Patient ID")
    parser.add_argument("--patient-name", help="Filter by Patient Name (wildcards allowed, e.g. 'Smith*')")
    parser.add_argument("--modality", help="Filter by Modality (CT, MR, US, DX, etc.)")
    parser.add_argument("--station-ae", help="Filter by Scheduled Station AE Title")
    parser.add_argument("--scheduled-date", help="Filter by Scheduled Date (YYYYMMDD)")
    parser.add_argument("--accession", help="Filter by Accession Number")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    query_mwl_scp(
        host=args.host,
        port=args.port,
        called_aet=args.called_aet,
        calling_aet=args.calling_aet,
        patient_id=args.patient_id,
        patient_name=args.patient_name,
        modality=args.modality,
        scheduled_date=args.scheduled_date,
        station_ae=args.station_ae,
        accession_number=args.accession,
    )
