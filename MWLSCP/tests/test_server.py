"""
Integration Tests for MWL SCP Server and SCU Client
===================================================
Tests C-ECHO and C-FIND operations over network loopback.
"""

import unittest
import tempfile
import shutil
import time
from pathlib import Path

from MWLSCP.config import ServerConfig
from MWLSCP.server import MWLServer
from MWLSCP.client import MWLClient, build_cfind_query
from MWLSCP.generator import create_sample_worklist_files


class TestMWLServerIntegration(unittest.TestCase):
    """End-to-end integration test of MWL SCP and SCU."""

    TEST_HOST = "127.0.0.1"
    TEST_PORT = 11199
    TEST_AET = "TEST_MWL_SCP"

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = Path(tempfile.mkdtemp())
        create_sample_worklist_files(cls.temp_dir)

        cls.config = ServerConfig(
            host=cls.TEST_HOST,
            port=cls.TEST_PORT,
            ae_title=cls.TEST_AET,
            worklists_dir=cls.temp_dir,
            log_level="WARNING",
            hot_reload=True,
        )
        cls.server = MWLServer(cls.config)
        cls.server.start(block=False)
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def setUp(self):
        self.client = MWLClient(calling_aet="TEST_SCU")

    def test_01_c_echo_verification(self):
        """Test DICOM C-ECHO ping against SCP."""
        result = self.client.echo(
            host=self.TEST_HOST,
            port=self.TEST_PORT,
            called_aet=self.TEST_AET,
        )
        self.assertTrue(result, "C-ECHO verification should succeed")

    def test_02_c_find_universal_query(self):
        """Test C-FIND query returning all available records."""
        results = self.client.query(
            host=self.TEST_HOST,
            port=self.TEST_PORT,
            called_aet=self.TEST_AET,
        )
        self.assertEqual(len(results), 5, "Universal query should return all 5 sample worklists")

    def test_03_c_find_modality_filter(self):
        """Test C-FIND filtered by Modality (CT)."""
        results = self.client.query(
            host=self.TEST_HOST,
            port=self.TEST_PORT,
            called_aet=self.TEST_AET,
            modality="CT",
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(str(results[0].PatientID), "P1001")
        self.assertEqual(str(results[0].ScheduledProcedureStepSequence[0].Modality), "CT")

    def test_04_c_find_patient_name_wildcard(self):
        """Test C-FIND with wildcard patient name (*Smith*)."""
        results = self.client.query(
            host=self.TEST_HOST,
            port=self.TEST_PORT,
            called_aet=self.TEST_AET,
            patient_name="*Smith*",
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(str(results[0].PatientID), "P1001")

    def test_05_c_find_no_match(self):
        """Test C-FIND with non-matching query returns empty list."""
        results = self.client.query(
            host=self.TEST_HOST,
            port=self.TEST_PORT,
            called_aet=self.TEST_AET,
            patient_id="NON_EXISTENT_ID",
        )
        self.assertEqual(len(results), 0)


if __name__ == "__main__":
    unittest.main()
