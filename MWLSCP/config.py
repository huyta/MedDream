"""
MWL SCP Server Configuration
============================
Defines default parameters and environment variable fallbacks for the MWL SCP server.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List
from pydicom.uid import (
    ExplicitVRLittleEndian,
    ImplicitVRLittleEndian,
    ExplicitVRBigEndian,
    DeflatedExplicitVRLittleEndian,
    UID,
)

# Standard DICOM SOP Class UIDs
SOP_CLASS_VERIFICATION = UID("1.2.840.10008.1.1")
SOP_CLASS_MODALITY_WORKLIST_FIND = UID("1.2.840.10008.5.1.4.31")

# Supported Transfer Syntaxes
DEFAULT_TRANSFER_SYNTAXES = [
    ExplicitVRLittleEndian,
    ImplicitVRLittleEndian,
    ExplicitVRBigEndian,
    DeflatedExplicitVRLittleEndian,
]


@dataclass
class ServerConfig:
    """Configuration settings for the MWL SCP server."""

    host: str = field(
        default_factory=lambda: os.environ.get("MWL_SCP_HOST", "0.0.0.0")
    )
    port: int = field(
        default_factory=lambda: int(os.environ.get("MWL_SCP_PORT", "11112"))
    )
    ae_title: str = field(
        default_factory=lambda: os.environ.get("MWL_SCP_AET", "MWL_SCP")
    )
    worklists_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("MWL_WORKLISTS_DIR", Path(__file__).resolve().parent / "worklists")
        )
    )
    log_level: str = field(
        default_factory=lambda: os.environ.get("MWL_LOG_LEVEL", "INFO").upper()
    )
    max_pdu_size: int = field(
        default_factory=lambda: int(os.environ.get("MWL_MAX_PDU", "16382"))
    )
    hot_reload: bool = True


def get_default_config() -> ServerConfig:
    """Get default server configuration with environment overrides."""
    return ServerConfig()
