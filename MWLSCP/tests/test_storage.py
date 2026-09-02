"""
Unit Tests for Worklist Directory Storage & Hot Reloading
"""

import unittest
import tempfile
import shutil
from pathlib import Path
import pydicom

from MWLSCP.storage import WorklistDirectoryStorage
from MWLSCP.generator import create_worklist_dataset, create_sample_worklist_files
from MWLSCP.client import build_cfind_query


class TestWorklistStorage(unittest.TestCase):
    """Test suite for worklist storage caching and hot reloading."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.storage = WorklistDirectoryStorage(self.temp_dir, hot_reload=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_empty_directory(self):
        self.assertEqual(len(self.storage.get_all()), 0)
        matches = self.storage.find_matches(build_cfind_query())
        self.assertEqual(len(matches), 0)

    def test_save_and_retrieve(self):
        ds = create_worklist_dataset(
            patient_id="P2001",
            patient_name="Tester^One",
            modality="MR",
        )
        saved_path = self.storage.save_worklist(ds, "test_mr.wl")
        self.assertTrue(saved_path.exists())

        items = self.storage.get_all()
        self.assertEqual(len(items), 1)

        summaries = self.storage.get_summary_list()
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["patient_id"], "P2001")
        self.assertEqual(summaries[0]["modality"], "MR")

    def test_hot_reload_on_new_file(self):
        # Initially empty
        self.assertEqual(len(self.storage.get_all()), 0)

        # Drop sample files
        create_sample_worklist_files(self.temp_dir)

        # Storage should immediately detect new files on get_all / find_matches
        items = self.storage.get_all()
        self.assertEqual(len(items), 5)

        # Query CT records
        ct_matches = self.storage.find_matches(build_cfind_query(modality="CT"))
        self.assertEqual(len(ct_matches), 1)
        self.assertEqual(str(ct_matches[0].PatientID), "P1001")

        # Query MR records
        mr_matches = self.storage.find_matches(build_cfind_query(modality="MR"))
        self.assertEqual(len(mr_matches), 2)


if __name__ == "__main__":
    unittest.main()
