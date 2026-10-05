#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from typing import Any, Dict, List, Optional
from Analyze_Label.utils import to_json_safe

REQUIRED_TOP_KEYS = {"scores", "rationales", "reasoning", "confidence"}
REQUIRED_SCORES_KEYS = {"C1", "C2"}
REQUIRED_RATIONALE_KEYS = {"C1", "C2"}


def _extract_first_json_object(text: str) -> str:
    """
    Extract the first top-level JSON object from arbitrary text by brace matching.
    Raises ValueError if no well-formed object is found.
    """
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


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def parse_prism_output(raw_text: str) -> Dict[str, Any]:
    """
    Parse and validate the LLM's JSON output for PRISM schema (no 'estimated_steps' or 'difficulty').

    Returns:
      {
        "ok": bool,
        "data": Dict | None,
        "errors": List[str],
        "snippet": str | None
      }
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

    # top-level keys
    missing = REQUIRED_TOP_KEYS - set(data.keys())
    if missing:
        errors.append(f"Missing top-level keys: {sorted(missing)}")

    # scores
    scores = data.get("scores")
    if not isinstance(scores, dict):
        errors.append("'scores' must be an object with keys C1 and C2.")
    else:
        missing_scores = REQUIRED_SCORES_KEYS - set(scores.keys())
        if missing_scores:
            errors.append(f"Missing score keys: {sorted(missing_scores)}")
        for k in REQUIRED_SCORES_KEYS:
            if k in scores:
                v = scores[k]
                if not _is_int(v) or not (0 <= v <= 3):
                    errors.append(f"'scores.{k}' must be an integer in [0,3], got: {v!r}")

    # rationales
    ration = data.get("rationales")
    if not isinstance(ration, dict):
        errors.append("'rationales' must be an object with keys C1 and C2 (short strings).")
    else:
        missing_rat = REQUIRED_RATIONALE_KEYS - set(ration.keys())
        if missing_rat:
            errors.append(f"Missing rationale keys: {sorted(missing_rat)}")
        for k in REQUIRED_RATIONALE_KEYS:
            if k in ration:
                v = ration[k]
                if not isinstance(v, str):
                    errors.append(f"'rationales.{k}' must be a string, got: {type(v).__name__}")

    # reasoning
    reasoning = data.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        errors.append("'reasoning' must be a non-empty string.")

    # confidence
    conf = data.get("confidence")
    try:
        conf_ok = _is_number(conf) and (0.0 <= float(conf) <= 1.0)
    except Exception:
        conf_ok = False
    if not conf_ok:
        errors.append("'confidence' must be a number in [0,1].")

    ok = len(errors) == 0
    return {"ok": ok, "data": data if ok else None, "errors": errors, "snippet": snippet}


# --------------------------
# Example usage
# --------------------------
if __name__ == "__main__":
    sample_output = (
        '''```json
{
  "scores": {"C1": 2, "C2": 2},
  "rationales": {
    "C1": "Involves gravitational dynamics and circular motion concepts.",
    "C2": "Moderate algebraic manipulation required for solving."
  },
  "reasoning": "Understanding of gravitational forces and centripetal motion with moderate algebra.",
  "confidence": 0.85
}
```'''
    )

    result = parse_prism_output(sample_output)
    print("OK:", result["ok"])
    if not result["ok"]:
        print("Errors:", result["errors"])
    else:
        print("Parsed C1:", result["data"]["scores"]["C1"])

    clean = to_json_safe(result)
    print(clean)