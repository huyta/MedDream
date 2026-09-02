"""
Worklist Storage and Repository Manager
======================================
Loads, caches, and hot-reloads DICOM Modality Worklist (.wl / .dcm) files
from the filesystem with high performance and zero external database overhead.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import pydicom
from pydicom.dataset import Dataset, FileDataset
from pydicom.sequence import Sequence

if __package__ is None or __package__ == "":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from matcher import MWLMatcher
else:
    from .matcher import MWLMatcher

logger = logging.getLogger("MWL_SCP.Storage")


class WorklistDirectoryStorage:
    """
    Filesystem-backed repository for DICOM Modality Worklist items.
    Supports automatic hot-reloading upon file modification.
    """

    def __init__(self, directory: Path, hot_reload: bool = True):
        self.directory = Path(directory)
        self.hot_reload = hot_reload
        self._cache: Dict[str, Tuple[float, Dataset]] = {}
        
        # Ensure worklists directory exists
        self.directory.mkdir(parents=True, exist_ok=True)
        self.refresh()

    def refresh(self, force: bool = False) -> int:
        """
        Scans the directory for .wl and .dcm files and updates the cache.
        Returns the total number of loaded worklists.
        """
        if not self.directory.exists():
            self._cache.clear()
            return 0

        valid_extensions = {".wl", ".dcm", ".dicom", ".dump"}
        current_files = set()

        try:
            for entry in os.scandir(self.directory):
                if entry.is_file():
                    ext = Path(entry.name).suffix.lower()
                    if ext in valid_extensions:
                        current_files.add(entry.path)
                        mtime = entry.stat().st_mtime
                        
                        # Load if new, modified, or forced
                        if force or entry.path not in self._cache or self._cache[entry.path][0] < mtime:
                            try:
                                ds = pydicom.dcmread(entry.path, force=True)
                                self._cache[entry.path] = (mtime, ds)
                                logger.debug("Loaded worklist file: %s", entry.name)
                            except Exception as err:
                                logger.warning("Failed to parse DICOM file %s: %s", entry.path, err)
        except Exception as err:
            logger.error("Error scanning directory %s: %s", self.directory, err)

        # Remove deleted files from cache
        removed_files = set(self._cache.keys()) - current_files
        for path in removed_files:
            del self._cache[path]
            logger.debug("Removed deleted file from cache: %s", path)

        return len(self._cache)

    def get_all(self) -> List[Tuple[str, Dataset]]:
        """Returns all loaded worklist items as (file_path, Dataset) pairs."""
        if self.hot_reload:
            self.refresh()
        return [(path, ds) for path, (_, ds) in self._cache.items()]

    def find_matches(self, query_dataset: Dataset) -> List[Dataset]:
        """
        Evaluates incoming C-FIND query against all worklist items and returns
        constructed response Datasets for matching items.
        """
        if self.hot_reload:
            self.refresh()

        matched_responses: List[Dataset] = []
        for path, (_, candidate_ds) in self._cache.items():
            try:
                if MWLMatcher.is_match(query_dataset, candidate_ds):
                    rsp_ds = MWLMatcher.build_response_dataset(query_dataset, candidate_ds)
                    matched_responses.append(rsp_ds)
            except Exception as err:
                logger.warning("Error matching candidate %s: %s", path, err)

        return matched_responses

    def save_worklist(self, dataset: Dataset, filename: Optional[str] = None) -> Path:
        """
        Saves a DICOM dataset as a .wl file in the storage directory.
        """
        self.directory.mkdir(parents=True, exist_ok=True)
        if not filename:
            pid = getattr(dataset, "PatientID", "unknown")
            acc = getattr(dataset, "AccessionNumber", "noacc")
            filename = f"mwl_{pid}_{acc}.wl"

        if not filename.endswith(".wl") and not filename.endswith(".dcm"):
            filename += ".wl"

        target_path = self.directory / filename
        pydicom.dcmwrite(target_path, dataset, enforce_file_format=True)
        self.refresh()
        logger.info("Saved worklist item to %s", target_path)
        return target_path

    def get_summary_list(self) -> List[Dict[str, Any]]:
        """Returns a list of structured summaries for all stored worklist items."""
        items = self.get_all()
        summaries = []

        for path, ds in items:
            # Extract Scheduled Procedure Step info
            modality = ""
            sps_date = ""
            sps_time = ""
            sps_desc = ""
            sps_station = ""
            sps_status = ""

            sps_seq = getattr(ds, "ScheduledProcedureStepSequence", None)
            if sps_seq and len(sps_seq) > 0:
                sps_item = sps_seq[0]
                modality = str(getattr(sps_item, "Modality", ""))
                sps_date = str(getattr(sps_item, "ScheduledProcedureStepStartDate", ""))
                sps_time = str(getattr(sps_item, "ScheduledProcedureStepStartTime", ""))
                sps_desc = str(getattr(sps_item, "ScheduledProcedureStepDescription", ""))
                sps_station = str(getattr(sps_item, "ScheduledStationAETitle", ""))
                sps_status = str(getattr(sps_item, "ScheduledProcedureStepStatus", ""))

            summary = {
                "file": Path(path).name,
                "file_path": path,
                "patient_id": str(getattr(ds, "PatientID", "")),
                "patient_name": str(getattr(ds, "PatientName", "")),
                "patient_sex": str(getattr(ds, "PatientSex", "")),
                "patient_dob": str(getattr(ds, "PatientBirthDate", "")),
                "accession_number": str(getattr(ds, "AccessionNumber", "")),
                "requested_procedure_desc": str(getattr(ds, "RequestedProcedureDescription", "")),
                "modality": modality,
                "scheduled_date": sps_date,
                "scheduled_time": sps_time,
                "scheduled_desc": sps_desc,
                "station_ae": sps_station,
                "status": sps_status,
                "study_instance_uid": str(getattr(ds, "StudyInstanceUID", "")),
            }
            summaries.append(summary)

        return sorted(summaries, key=lambda x: (x["scheduled_date"], x["scheduled_time"]))
