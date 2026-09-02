"""
MWLSCP - DICOM Modality Worklist (MWL) SCP Provider Package
===========================================================
A clean, lightweight, and standards-compliant DICOM Modality Worklist
SCP server and SCU client built on pydicom and pynetdicom.
"""

from .config import ServerConfig, get_default_config
from .matcher import MWLMatcher
from .storage import WorklistDirectoryStorage
from .server import MWLServer, run_server_cli
from .client import MWLClient, build_cfind_query, format_mwl_results_table
from .generator import create_worklist_dataset, create_sample_worklist_files

__version__ = "1.0.0"

__all__ = [
    "MWLServer",
    "ServerConfig",
    "get_default_config",
    "MWLMatcher",
    "WorklistDirectoryStorage",
    "MWLClient",
    "build_cfind_query",
    "format_mwl_results_table",
    "create_worklist_dataset",
    "create_sample_worklist_files",
    "run_server_cli",
]
