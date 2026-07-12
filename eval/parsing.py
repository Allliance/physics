"""Multipart detection, box extraction, and robust judge-output parsing."""

from __future__ import annotations

import json
import re
from typing import Any

_BOX = re.compile(r"\\boxed\s*\{")
_LABEL = re.compile(r"^\s*\(?\s*([a-zA-Z])\s*\)?\s*(?:[:.)-]\s*)?", re.S)


def detect_part_ids(ground_truths: dict[str, str]) -> list[str]:
    """Use the ground-truth dictionary keys as the authoritative part IDs."""
    parts = list(ground_truths)
    if not parts:
        raise ValueError("ground_truths must contain at least one part")
    if any(not isinstance(part, str) or not part for part in parts):
        raise ValueError("ground_truths keys must be non-empty strings")
    return parts


def extract_boxes(text: str) -> list[str]:
    """Extract balanced brace content from LaTeX boxes, including nested braces."""
    boxes: list[str] = []
    for match in _BOX.finditer(text):
        depth, escaped, i = 1, False, match.end()
        start = i
        while i < len(text) and depth:
            char = text[i]
            if char == "{" and not escaped:
                depth += 1
            elif char == "}" and not escaped:
                depth -= 1
                if depth == 0:
                    boxes.append(text[start:i].strip())
                    break
            escaped = char == "\\" and not escaped
            if char != "\\":
                escaped = False
            i += 1
    return boxes


def strip_part_label(answer: str) -> str:
    """Remove one leading part label from extracted answer content."""
    match = _LABEL.match(answer)
    return answer[match.end():].strip() if match else answer.strip()


def map_separated_boxes(boxes: list[str], part_ids: list[str]) -> tuple[dict[str, str], list[str]]:
    answers: dict[str, str] = {}
    errors: list[str] = []
    for index, box in enumerate(boxes):
        match = _LABEL.match(box)
        supplied_label = match.group(1).lower() if match else None
        label = supplied_label
        if label not in part_ids:
            label = part_ids[index] if index < len(part_ids) else None
            errors.append(f"box {index + 1} lacked a valid label; assigned by position")
        content = strip_part_label(box)
        if label is not None and label not in answers:
            answers[label] = content
        elif label is not None:
            errors.append(f"duplicate box for part {label}")
    if len(boxes) != len(part_ids):
        errors.append(f"expected {len(part_ids)} boxes, found {len(boxes)}")
    for part in part_ids:
        answers.setdefault(part, "")
    return answers, errors


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise ValueError(f"No JSON object in judge response: {text!r}")
        value = json.loads(match.group())
    if not isinstance(value, dict):
        raise ValueError("Judge response is not a JSON object")
    return value
