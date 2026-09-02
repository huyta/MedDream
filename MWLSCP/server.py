"""
DICOM Modality Worklist (MWL) SCP Server
========================================
Implements a DICOM Service Class Provider (SCP) for:
- Verification SOP Class (1.2.840.10008.1.1 - C-ECHO)
- Modality Worklist Information Model - FIND (1.2.840.10008.5.1.4.31 - C-FIND)
"""

import sys
import signal
import logging
from typing import Optional, List, Tuple
from pathlib import Path

import pydicom
from pydicom.dataset import Dataset
from pynetdicom import AE, evt, AllStoragePresentationContexts
from pynetdicom.sop_class import (
    Verification,
    ModalityWorklistInformationFind,
)

if __package__ is None or __package__ == "":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from config import ServerConfig, DEFAULT_TRANSFER_SYNTAXES, get_default_config
    from storage import WorklistDirectoryStorage
else:
    from .config import ServerConfig, DEFAULT_TRANSFER_SYNTAXES, get_default_config
    from .storage import WorklistDirectoryStorage

logger = logging.getLogger("MWL_SCP")


def _clean_aet(aet) -> str:
    """Helper to convert bytes or string AE title to a clean string."""
    if isinstance(aet, bytes):
        return aet.decode("ascii", errors="ignore").strip()
    return str(aet).strip()


class MWLServer:
    """
    DICOM Modality Worklist SCP Server.
    Provides standard C-ECHO and C-FIND services to imaging modalities.
    """

    def __init__(self, config: Optional[ServerConfig] = None):
        self.config = config or get_default_config()
        self.storage = WorklistDirectoryStorage(
            self.config.worklists_dir,
            hot_reload=self.config.hot_reload,
        )
        self.ae = AE(ae_title=_clean_aet(self.config.ae_title))
        self.ae.maximum_pdu_size = self.config.max_pdu_size

        # Register supported contexts
        self._setup_presentation_contexts()

        # Internal server handle
        self._server = None
        self._is_running = False

    def _setup_presentation_contexts(self) -> None:
        """Register DICOM verification and MWL C-FIND presentation contexts."""
        self.ae.add_supported_context(Verification, DEFAULT_TRANSFER_SYNTAXES)
        self.ae.add_supported_context(
            ModalityWorklistInformationFind, DEFAULT_TRANSFER_SYNTAXES
        )

    def _format_query_summary(self, query: Dataset) -> str:
        """Formats a one-line summary of non-empty search filters in the query."""
        filters = []
        if "PatientID" in query and query.PatientID:
            filters.append(f"PatientID='{query.PatientID}'")
        if "PatientName" in query and query.PatientName:
            filters.append(f"PatientName='{query.PatientName}'")
        if "AccessionNumber" in query and query.AccessionNumber:
            filters.append(f"Accession='{query.AccessionNumber}'")
        
        sps_seq = getattr(query, "ScheduledProcedureStepSequence", None)
        if sps_seq and len(sps_seq) > 0:
            sps_item = sps_seq[0]
            if "Modality" in sps_item and sps_item.Modality:
                filters.append(f"Modality='{sps_item.Modality}'")
            if "ScheduledProcedureStepStartDate" in sps_item and sps_item.ScheduledProcedureStepStartDate:
                filters.append(f"Date='{sps_item.ScheduledProcedureStepStartDate}'")
            if "ScheduledStationAETitle" in sps_item and sps_item.ScheduledStationAETitle:
                filters.append(f"StationAE='{sps_item.ScheduledStationAETitle}'")

        return ", ".join(filters) if filters else "Universal Query (All entries requested)"

    def handle_c_echo(self, event: evt.Event) -> int:
        """Handles C-ECHO verification requests (DICOM ping)."""
        calling_aet = _clean_aet(event.assoc.requestor.ae_title)
        addr, port = event.assoc.requestor.address, event.assoc.requestor.port
        logger.info("[C-ECHO] Received verification request from '%s' (%s:%s) -> Success (0x0000)", calling_aet, addr, port)
        return 0x0000

    def handle_c_find(self, event: evt.Event):
        """
        Handles C-FIND requests for Modality Worklist Information Model.
        Yields (status, dataset) pairs.
        """
        calling_aet = _clean_aet(event.assoc.requestor.ae_title)
        addr, port = event.assoc.requestor.address, event.assoc.requestor.port
        query_ds = event.identifier

        query_summary = self._format_query_summary(query_ds)
        logger.info("[C-FIND] Worklist query from '%s' (%s:%s) | Filter: %s", calling_aet, addr, port, query_summary)

        try:
            matches = self.storage.find_matches(query_ds)
            match_count = len(matches)
            logger.info("[C-FIND] Found %d matching worklist item(s)", match_count)

            for idx, match_ds in enumerate(matches, 1):
                if event.is_cancelled:
                    logger.warning("[C-FIND] Query cancelled by client '%s'", calling_aet)
                    yield (0xFE00, None)
                    return

                # Extract basic identifiers for logging
                pid = getattr(match_ds, "PatientID", "N/A")
                pname = getattr(match_ds, "PatientName", "N/A")
                acc = getattr(match_ds, "AccessionNumber", "N/A")
                logger.debug("[C-FIND] Sending match %d/%d: %s (%s, Acc: %s)", idx, match_count, pname, pid, acc)

                # 0xFF00: Pending - Match is supplied
                yield (0xFF00, match_ds)

            # 0x0000: Success - Matching complete
            logger.info("[C-FIND] Completed responding to '%s' (%d records sent)", calling_aet, match_count)
            yield (0x0000, None)

        except Exception as err:
            logger.exception("[C-FIND] Error processing query: %s", err)
            # 0xC000: Unable to process
            yield (0xC000, None)

    def handle_association_accepted(self, event: evt.Event) -> None:
        """Handles association established event."""
        calling_aet = _clean_aet(event.assoc.requestor.ae_title)
        called_aet = _clean_aet(event.assoc.acceptor.ae_title)
        addr = event.assoc.requestor.address
        logger.debug("[ASSOC] Accepted association: Calling '%s' -> Called '%s' from %s", calling_aet, called_aet, addr)

    def handle_association_released(self, event: evt.Event) -> None:
        """Handles association released event."""
        calling_aet = _clean_aet(event.assoc.requestor.ae_title)
        logger.debug("[ASSOC] Association released by '%s'", calling_aet)

    def start(self, block: bool = True) -> None:
        """Starts the MWL SCP server."""
        handlers = [
            (evt.EVT_C_ECHO, self.handle_c_echo),
            (evt.EVT_C_FIND, self.handle_c_find),
            (evt.EVT_ACCEPTED, self.handle_association_accepted),
            (evt.EVT_RELEASED, self.handle_association_released),
        ]

        logger.info("=" * 60)
        logger.info(" DICOM Modality Worklist (MWL) SCP Server")
        logger.info("=" * 60)
        logger.info(" AE Title       : %s", self.config.ae_title)
        logger.info(" Listening on   : %s:%d", self.config.host, self.config.port)
        logger.info(" Worklists Dir  : %s", self.config.worklists_dir.resolve())
        
        count = self.storage.refresh()
        logger.info(" Active Records : %d worklist file(s) loaded", count)
        logger.info(" Hot Reloading  : %s", "Enabled" if self.config.hot_reload else "Disabled")
        logger.info("=" * 60)

        self._is_running = True
        self._server = self.ae.start_server(
            (self.config.host, self.config.port),
            block=block,
            evt_handlers=handlers,
        )

    def stop(self) -> None:
        """Stops the MWL SCP server."""
        if self._server and self._is_running:
            logger.info("Shutting down MWL SCP server...")
            self._server.shutdown()
            self._is_running = False
            logger.info("MWL SCP server stopped.")


def run_server_cli(config: Optional[ServerConfig] = None) -> None:
    """Entrypoint to run the server with graceful signal handling."""
    cfg = config or get_default_config()
    
    # Configure logging format
    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    server = MWLServer(cfg)

    def handle_signal(sig, frame):
        logger.info("Interrupt received (%s), exiting...", sig)
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        server.start(block=True)
    except Exception as err:
        logger.error("Failed to start server: %s", err)
        sys.exit(1)


if __name__ == "__main__":
    run_server_cli()
