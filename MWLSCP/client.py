"""
DICOM Modality Worklist (MWL) SCU Client
=======================================
Provides C-ECHO (verification) and C-FIND (worklist query) client functionality
for testing and interacting with any DICOM MWL SCP server.
"""

import sys
import logging
from typing import Optional, List, Dict, Any, Tuple
import pydicom
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from pynetdicom import AE
from pynetdicom.sop_class import (
    Verification,
    ModalityWorklistInformationFind,
)

if __package__ is None or __package__ == "":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from config import DEFAULT_TRANSFER_SYNTAXES
else:
    from .config import DEFAULT_TRANSFER_SYNTAXES

logger = logging.getLogger("MWL_SCU")


def build_cfind_query(
    patient_id: Optional[str] = None,
    patient_name: Optional[str] = None,
    modality: Optional[str] = None,
    scheduled_date: Optional[str] = None,
    station_ae: Optional[str] = None,
    accession_number: Optional[str] = None,
    requested_procedure_id: Optional[str] = None,
) -> Dataset:
    """
    Constructs a standard DICOM Modality Worklist C-FIND query dataset
    populated with return keys and search filters.
    """
    ds = Dataset()

    # Patient Identification and Demographics
    ds.PatientName = patient_name or ""
    ds.PatientID = patient_id or ""
    ds.PatientBirthDate = ""
    ds.PatientSex = ""
    ds.PatientWeight = ""
    ds.MedicalAlerts = ""
    ds.Allergies = ""

    # Procedure Information
    ds.StudyInstanceUID = ""
    ds.AccessionNumber = accession_number or ""
    ds.RequestedProcedureID = requested_procedure_id or ""
    ds.RequestedProcedureDescription = ""
    ds.RequestedProcedurePriority = ""
    ds.ReferringPhysicianName = ""
    ds.InstitutionName = ""

    # Scheduled Procedure Step Sequence (0040,0100)
    sps = Dataset()
    sps.ScheduledStationAETitle = station_ae or ""
    sps.ScheduledStationName = ""
    sps.ScheduledProcedureStepStartDate = scheduled_date or ""
    sps.ScheduledProcedureStepStartTime = ""
    sps.Modality = modality or ""
    sps.ScheduledPerformingPhysicianName = ""
    sps.ScheduledProcedureStepDescription = ""
    sps.ScheduledProcedureStepID = ""
    sps.ScheduledProcedureStepLocation = ""
    sps.ScheduledProcedureStepStatus = ""

    ds.ScheduledProcedureStepSequence = Sequence([sps])
    return ds


def _clean_aet(aet) -> str:
    """Helper to convert bytes or string AE title to a clean string."""
    if isinstance(aet, bytes):
        return aet.decode("ascii", errors="ignore").strip()
    return str(aet).strip()


class MWLClient:
    """
    SCU Client for DICOM Modality Worklist queries and verification.
    """

    def __init__(self, calling_aet: str = "MWL_SCU"):
        self.calling_aet = _clean_aet(calling_aet)
        self.ae = AE(ae_title=self.calling_aet)
        self.ae.add_requested_context(Verification, DEFAULT_TRANSFER_SYNTAXES)
        self.ae.add_requested_context(
            ModalityWorklistInformationFind, DEFAULT_TRANSFER_SYNTAXES
        )

    def echo(self, host: str, port: int, called_aet: str = "MWL_SCP") -> bool:
        """Sends a C-ECHO verification request to the SCP server."""
        assoc = self.ae.associate(
            host, port, ae_title=_clean_aet(called_aet)
        )
        if not assoc.is_established:
            logger.error("Failed to establish association with %s:%d (%s)", host, port, called_aet)
            return False

        try:
            status = assoc.send_c_echo()
            if status and status.Status == 0x0000:
                logger.info("C-ECHO to %s:%d [%s] SUCCESSFUL (0x0000)", host, port, called_aet)
                return True
            else:
                logger.error("C-ECHO returned status: %s", hex(status.Status) if status else "None")
                return False
        finally:
            assoc.release()

    def query(
        self,
        host: str,
        port: int,
        called_aet: str = "MWL_SCP",
        query_dataset: Optional[Dataset] = None,
        **filters,
    ) -> List[Dataset]:
        """
        Sends a C-FIND request to the SCP and returns all matching Datasets.
        """
        assoc = self.ae.associate(
            host, port, ae_title=_clean_aet(called_aet)
        )
        if not assoc.is_established:
            raise ConnectionError(
                f"Could not establish DICOM association with {host}:{port} [{called_aet}]"
            )

        if query_dataset is None:
            query_dataset = build_cfind_query(**filters)

        results: List[Dataset] = []
        try:
            responses = assoc.send_c_find(
                query_dataset, ModalityWorklistInformationFind
            )
            for status, identifier in responses:
                if status:
                    if status.Status in (0xFF00, 0xFF01) and identifier:
                        results.append(identifier)
                    elif status.Status == 0x0000:
                        logger.debug("C-FIND query completed with SUCCESS (0x0000)")
                    elif status.Status == 0xFE00:
                        logger.warning("C-FIND query was CANCELLED (0xFE00)")
                    else:
                        logger.warning("C-FIND returned non-success status: 0x%04X", status.Status)
        finally:
            assoc.release()

        return results


def format_mwl_results_table(results: List[Dataset]) -> str:
    """Formats a list of MWL Datasets into a clean tabular ASCII report."""
    if not results:
        return "No Modality Worklist records found matching query criteria."

    headers = [
        "Patient ID",
        "Patient Name",
        "Sex",
        "Modality",
        "Date",
        "Time",
        "Accession",
        "Procedure Description",
        "Station AE",
    ]
    rows = []

    for ds in results:
        pid = str(getattr(ds, "PatientID", ""))
        pname = str(getattr(ds, "PatientName", ""))
        psex = str(getattr(ds, "PatientSex", ""))
        acc = str(getattr(ds, "AccessionNumber", ""))
        req_desc = str(getattr(ds, "RequestedProcedureDescription", ""))

        modality = ""
        date_str = ""
        time_str = ""
        station_ae = ""

        sps_seq = getattr(ds, "ScheduledProcedureStepSequence", None)
        if sps_seq and len(sps_seq) > 0:
            sps = sps_seq[0]
            modality = str(getattr(sps, "Modality", ""))
            date_str = str(getattr(sps, "ScheduledProcedureStepStartDate", ""))
            time_str = str(getattr(sps, "ScheduledProcedureStepStartTime", ""))
            station_ae = str(getattr(sps, "ScheduledStationAETitle", ""))
            if not req_desc:
                req_desc = str(getattr(sps, "ScheduledProcedureStepDescription", ""))

        # Format date YYYYMMDD -> YYYY-MM-DD
        if len(date_str) == 8 and date_str.isdigit():
            date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

        # Format time HHMMSS -> HH:MM:SS
        if len(time_str) >= 6 and time_str[:6].isdigit():
            time_str = f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"

        rows.append([
            pid[:12],
            pname[:20],
            psex[:3],
            modality[:8],
            date_str[:10],
            time_str[:8],
            acc[:14],
            req_desc[:30],
            station_ae[:12],
        ])

    # Compute column widths
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(val))

    # Construct table
    sep_line = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"

    output_lines = [sep_line, header_line, sep_line]
    for row in rows:
        row_line = "| " + " | ".join(val.ljust(col_widths[i]) for i, val in enumerate(row)) + " |"
        output_lines.append(row_line)
    output_lines.append(sep_line)
    output_lines.append(f"Total matching items: {len(results)}")

    return "\n".join(output_lines)
