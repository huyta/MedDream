"""
DICOM Modality Worklist (MWL) Matching Engine
=============================================
Implements DICOM PS 3.4 compliant matching for C-FIND requests:
- Single Value Matching (exact match)
- Wildcard Matching (* and ?)
- Date and Date-Range Matching (YYYYMMDD-YYYYMMDD, YYYYMMDD-, -YYYYMMDD)
- Sequence Matching (ScheduledProcedureStepSequence 0040,0100)
- Return Key filtering & Dataset construction
"""

import re
import fnmatch
from typing import Any, Optional, List, Tuple
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from pydicom.dataelem import DataElement
from pydicom.tag import Tag, BaseTag


def match_single_value(query_val: Any, target_val: Any, case_sensitive: bool = False) -> bool:
    """Check if single non-wildcard value matches target."""
    if query_val is None or target_val is None:
        return False
    
    q_str = str(query_val).strip()
    t_str = str(target_val).strip()
    
    if not case_sensitive:
        return q_str.lower() == t_str.lower()
    return q_str == t_str


def match_wildcard(pattern: str, target_val: Any, case_sensitive: bool = False) -> bool:
    """
    Check if target matches wildcard pattern containing '*' or '?'.
    DICOM standard: '*' matches any sequence of characters, '?' matches a single character.
    """
    if target_val is None:
        return False
    
    t_str = str(target_val).strip()
    p_str = pattern.strip()
    
    if not case_sensitive:
        return fnmatch.fnmatch(t_str.lower(), p_str.lower())
    return fnmatch.fnmatchcase(t_str, p_str)


def match_date_range(query_date_str: str, target_date_str: Any) -> bool:
    """
    Match DICOM DA date or date range.
    Formats supported:
    - 'YYYYMMDD' (Single date match)
    - 'YYYYMMDD-YYYYMMDD' (Range inclusive)
    - 'YYYYMMDD-' (From date onwards)
    - '-YYYYMMDD' (Up to date)
    """
    if target_date_str is None:
        return False
    
    # Normalize target date
    t_date = str(target_date_str).replace("-", "").replace("/", "").strip()
    q_date = str(query_date_str).strip()
    
    if "-" in q_date:
        parts = q_date.split("-", 1)
        start_date = parts[0].replace("-", "").replace("/", "").strip()
        end_date = parts[1].replace("-", "").replace("/", "").strip()
        
        if start_date and end_date:
            return start_date <= t_date <= end_date
        elif start_date:
            return t_date >= start_date
        elif end_date:
            return t_date <= end_date
        return True  # '-' matches all
    else:
        q_clean = q_date.replace("-", "").replace("/", "").strip()
        return t_date == q_clean


def match_element(query_elem: DataElement, target_dataset: Dataset) -> bool:
    """
    Evaluates whether a single query attribute matches the target dataset.
    Empty query elements are considered universal matches (Return Keys).
    """
    tag = query_elem.tag
    
    # If attribute is missing in target and query has non-empty filter, no match
    if tag not in target_dataset:
        # If query value is empty or None, it's a return key request, so it's a match
        return query_elem.value is None or query_elem.value == "" or query_elem.value == []
    
    target_elem = target_dataset[tag]
    query_val = query_elem.value
    target_val = target_elem.value
    
    # Universal match check: empty string, empty list, or None
    if query_val is None or query_val == "" or query_val == []:
        return True
    
    # Sequence matching
    if query_elem.VR == "SQ":
        return match_sequence(query_elem, target_dataset)
    
    # Date matching (DA)
    if query_elem.VR == "DA":
        return match_date_range(str(query_val), target_val)
    
    # Person Name (PN) or String with wildcards
    q_str = str(query_val)
    if "*" in q_str or "?" in q_str:
        return match_wildcard(q_str, target_val, case_sensitive=False)
    
    # String / UID / Code matching
    # Case-insensitive for strings, exact for numbers/UIDs
    case_sensitive = query_elem.VR in ("UI", "OB", "OW", "UN")
    return match_single_value(query_val, target_val, case_sensitive=case_sensitive)


def match_sequence(query_elem: DataElement, target_dataset: Dataset) -> bool:
    """
    Match sequence attributes, especially ScheduledProcedureStepSequence (0040,0100).
    A sequence in query matches if any item in target sequence satisfies the query item.
    """
    tag = query_elem.tag
    if tag not in target_dataset:
        return False
    
    query_seq = query_elem.value
    target_seq = target_dataset[tag].value
    
    # If query sequence is empty or has no items, universal match
    if not query_seq or len(query_seq) == 0:
        return True
    
    # If target sequence is empty but query specified criteria, no match
    if not target_seq or len(target_seq) == 0:
        return False
    
    # In DICOM C-FIND, query sequence typically has 1 template item
    query_item = query_seq[0] if isinstance(query_seq, (list, Sequence)) else query_seq
    if not isinstance(query_item, Dataset):
        return True
    
    # Check if ANY target sequence item matches all query attributes in the sequence
    for target_item in target_seq:
        item_matches = True
        for elem in query_item:
            if not match_element(elem, target_item):
                item_matches = False
                break
        if item_matches:
            return True
            
    return False


class MWLMatcher:
    """
    DICOM Modality Worklist C-FIND Matcher.
    Compares incoming C-FIND Identifier dataset against a candidate worklist Dataset.
    """

    @staticmethod
    def is_match(query_dataset: Dataset, candidate_dataset: Dataset) -> bool:
        """
        Determine whether a candidate worklist dataset satisfies all search keys
        specified in the query dataset.
        """
        if query_dataset is None or len(query_dataset) == 0:
            return True

        for elem in query_dataset:
            # Skip file meta group length or group 0x0000 command elements if present
            if elem.tag.group in (0x0000, 0x0002):
                continue
            
            if not match_element(elem, candidate_dataset):
                return False
                
        return True

    @staticmethod
    def build_response_dataset(query_dataset: Dataset, candidate_dataset: Dataset) -> Dataset:
        """
        Constructs the C-FIND response Dataset containing the requested return keys
        populated with values from the candidate dataset.
        """
        response = Dataset()

        # Always include character set if present in candidate
        if "SpecificCharacterSet" in candidate_dataset:
            response.SpecificCharacterSet = candidate_dataset.SpecificCharacterSet

        # If query is empty, return entire candidate dataset (minus meta elements)
        if query_dataset is None or len(query_dataset) == 0:
            for elem in candidate_dataset:
                if elem.tag.group not in (0x0000, 0x0002):
                    response.add(elem)
            return response

        # Populate requested attributes from query
        for elem in query_dataset:
            tag = elem.tag
            if tag.group in (0x0000, 0x0002):
                continue

            if tag in candidate_dataset:
                target_elem = candidate_dataset[tag]
                
                # Handle sequence response reconstruction
                if elem.VR == "SQ" and isinstance(target_elem.value, (list, Sequence)):
                    query_seq = elem.value
                    target_seq = target_elem.value
                    
                    resp_seq = Sequence()
                    query_item_template = query_seq[0] if query_seq and len(query_seq) > 0 and isinstance(query_seq[0], Dataset) else None
                    
                    for t_item in target_seq:
                        if query_item_template is not None and len(query_item_template) > 0:
                            # Build response item using query template return keys
                            resp_item = Dataset()
                            for sub_elem in query_item_template:
                                sub_tag = sub_elem.tag
                                if sub_tag in t_item:
                                    resp_item.add(t_item[sub_tag])
                                else:
                                    # Include empty attribute for requested key if missing in candidate
                                    resp_item.add_new(sub_tag, sub_elem.VR, "")
                            resp_seq.append(resp_item)
                        else:
                            # Full sequence item if template was empty
                            resp_seq.append(t_item)
                            
                    response.add_new(tag, "SQ", resp_seq)
                else:
                    response.add(target_elem)
            else:
                # DICOM C-FIND return key requested by SCU but not present in candidate
                # Return empty element with requested VR
                response.add_new(tag, elem.VR, "")

        # Ensure essential Modality Worklist mandatory return keys exist in response
        essential_keys = [
            ("PatientName", "PN"),
            ("PatientID", "LO"),
            ("StudyInstanceUID", "UI"),
            ("AccessionNumber", "SH"),
        ]
        for key_name, vr in essential_keys:
            if key_name not in response and key_name in candidate_dataset:
                response.add(candidate_dataset[key_name])

        return response
