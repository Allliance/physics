#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import math
from typing import Any, Dict, List, Optional

ALLOWED_PRIMARY_ERRORS = {"DAE", "PTAE", "MPUE", "CAE", "VRE", "DCE", "UDE", "Uncertain"}
ALLOWED_SECONDARY_ERRORS = {"DAE", "PTAE", "MPUE", "CAE", "VRE", "DCE", "UDE"}
ALLOWED_UNIT_STATUS = {"consistent", "inconsistent", "not-applicable", "unknown"}
ALLOWED_ASSUMPTION_STATUS = {"none", "present", "unknown"}

REQUIRED_TOP_KEYS = {
    "primary_error", "secondary_errors", "incorrect_expressions",
    "related_correct_expressions", "unit_dimension_status", "assumption_mismatch",
    "rationale", "confidence"
}


def _extract_first_json_object(text: str) -> str:
    """Extract the first top-level JSON object from arbitrary text by brace matching."""
    start = text.find("{")
    if start == -1:
        raise ValueError("No '{' found in model output.")
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise ValueError("Unbalanced braces; could not extract a complete JSON object.")


def _is_str_list(v: Any) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def parse_error_analysis_output(raw_text: str) -> Dict[str, Any]:
    """
    Parse and validate the LLM's JSON output according to the error analysis schema.
    """
    errors: List[str] = []
    snippet: Optional[str] = None

    try:
        snippet = _extract_first_json_object(raw_text)
    except ValueError as e:
        return {"ok": False, "data": None, "errors": [f"Extraction error: {e}"], "snippet": None}

    try:
        data = json.loads(snippet)
    except json.JSONDecodeError as e:
        return {"ok": False, "data": None, "errors": [f"JSON decode error: {e}"], "snippet": snippet}

    if not isinstance(data, dict):
        return {"ok": False, "data": None, "errors": ["Top-level JSON must be an object."], "snippet": snippet}

    # Check required keys
    missing = REQUIRED_TOP_KEYS - set(data.keys())
    if missing:
        errors.append(f"Missing top-level keys: {sorted(missing)}")

    # primary_error
    pe = data.get("primary_error")
    if pe not in ALLOWED_PRIMARY_ERRORS:
        errors.append(f"'primary_error' must be one of {sorted(ALLOWED_PRIMARY_ERRORS)}, got: {pe!r}")

    # secondary_errors
    se = data.get("secondary_errors")
    if not _is_str_list(se) or not all(s in ALLOWED_SECONDARY_ERRORS for s in se):
        errors.append(f"'secondary_errors' must be a list of {sorted(ALLOWED_SECONDARY_ERRORS)}.")

    # incorrect_expressions
    if not _is_str_list(data.get("incorrect_expressions", [])):
        errors.append("'incorrect_expressions' must be a list of strings.")

    # related_correct_expressions
    if not _is_str_list(data.get("related_correct_expressions", [])):
        errors.append("'related_correct_expressions' must be a list of strings.")

    # unit_dimension_status
    uds = data.get("unit_dimension_status")
    if uds not in ALLOWED_UNIT_STATUS:
        errors.append(f"'unit_dimension_status' must be one of {sorted(ALLOWED_UNIT_STATUS)}, got: {uds!r}")

    # assumption_mismatch
    am = data.get("assumption_mismatch")
    if am not in ALLOWED_ASSUMPTION_STATUS:
        errors.append(f"'assumption_mismatch' must be one of {sorted(ALLOWED_ASSUMPTION_STATUS)}, got: {am!r}")

    # rationale
    if not isinstance(data.get("rationale"), str) or not data["rationale"].strip():
        errors.append("'rationale' must be a non-empty string.")

    # confidence
    conf = data.get("confidence")
    if not (_is_number(conf) and 0.0 <= float(conf) <= 1.0):
        errors.append("'confidence' must be a number in [0,1].")

    ok = len(errors) == 0
    return {"ok": ok, "data": data if ok else None, "errors": errors, "snippet": snippet}

