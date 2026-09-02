"""
Unit Tests for MWL Matching Engine
"""

import unittest
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence

from MWLSCP.matcher import (
    MWLMatcher,
    match_single_value,
    match_wildcard,
    match_date_range,
)
from MWLSCP.generator import create_worklist_dataset
from MWLSCP.client import build_cfind_query


class TestMWLMatcher(unittest.TestCase):
    """Test suite for DICOM C-FIND matching rules."""

    def setUp(self):
        self.candidate = create_worklist_dataset(
            patient_id="P1001",
            patient_name="Smith^John^A",
            patient_sex="M",
            patient_dob="19800515",
            accession_number="ACC20260901001",
            modality="CT",
            scheduled_date="20260902",
            scheduled_time="090000",
            scheduled_station_ae="CT_SCANNER_1",
            requested_procedure_desc="CT Chest with IV Contrast",
        )

    def test_single_value_match(self):
        self.assertTrue(match_single_value("P1001", "P1001"))
        self.assertTrue(match_single_value("p1001", "P1001", case_sensitive=False))
        self.assertFalse(match_single_value("p1001", "P1001", case_sensitive=True))
        self.assertFalse(match_single_value("P1002", "P1001"))

    def test_wildcard_match(self):
        self.assertTrue(match_wildcard("Smith*", "Smith^John^A"))
        self.assertTrue(match_wildcard("*John*", "Smith^John^A"))
        self.assertTrue(match_wildcard("Sm?th*", "Smith^John^A"))
        self.assertTrue(match_wildcard("*", "Any Value"))
        self.assertFalse(match_wildcard("Doe*", "Smith^John^A"))

    def test_date_range_match(self):
        # Exact date
        self.assertTrue(match_date_range("20260902", "20260902"))
        self.assertFalse(match_date_range("20260901", "20260902"))

        # Range YYYYMMDD-YYYYMMDD
        self.assertTrue(match_date_range("20260901-20260905", "20260902"))
        self.assertTrue(match_date_range("20260902-20260902", "20260902"))
        self.assertFalse(match_date_range("20260903-20260910", "20260902"))

        # Open-ended ranges
        self.assertTrue(match_date_range("20260901-", "20260902"))
        self.assertFalse(match_date_range("20260903-", "20260902"))
        self.assertTrue(match_date_range("-20260905", "20260902"))
        self.assertFalse(match_date_range("-20260901", "20260902"))

    def test_universal_query(self):
        query = Dataset()
        query.PatientName = ""
        query.PatientID = ""
        query.StudyInstanceUID = ""
        self.assertTrue(MWLMatcher.is_match(query, self.candidate))

    def test_matching_by_patient_id(self):
        query = Dataset()
        query.PatientID = "P1001"
        self.assertTrue(MWLMatcher.is_match(query, self.candidate))

        query.PatientID = "P9999"
        self.assertFalse(MWLMatcher.is_match(query, self.candidate))

    def test_matching_by_modality_sequence(self):
        query = build_cfind_query(modality="CT")
        self.assertTrue(MWLMatcher.is_match(query, self.candidate))

        query_mr = build_cfind_query(modality="MR")
        self.assertFalse(MWLMatcher.is_match(query_mr, self.candidate))

    def test_matching_by_date_and_station_ae(self):
        query = build_cfind_query(
            scheduled_date="20260901-20260903",
            station_ae="CT_SCANNER_1",
            modality="CT",
        )
        self.assertTrue(MWLMatcher.is_match(query, self.candidate))

        query_wrong_ae = build_cfind_query(
            scheduled_date="20260901-20260903",
            station_ae="MR_ROOM_1",
        )
        self.assertFalse(MWLMatcher.is_match(query_wrong_ae, self.candidate))

    def test_build_response_dataset(self):
        query = build_cfind_query(patient_id="P1001")
        response = MWLMatcher.build_response_dataset(query, self.candidate)

        self.assertEqual(str(response.PatientID), "P1001")
        self.assertEqual(str(response.PatientName), "Smith^John^A")
        self.assertEqual(str(response.AccessionNumber), "ACC20260901001")
        self.assertIn("ScheduledProcedureStepSequence", response)
        self.assertEqual(
            str(response.ScheduledProcedureStepSequence[0].Modality), "CT"
        )


if __name__ == "__main__":
    unittest.main()
