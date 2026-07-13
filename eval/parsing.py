"""Multipart detection, box extraction, and robust judge-output parsing."""

from __future__ import annotations

import json
import re
from typing import Any

_BOX = re.compile(r"\\boxed\s*\{")
_LABEL = re.compile(
    r"^(?:(?:\s|%)+|\\[,;:!]\s*)*(?:"
    r"\(\s*([a-zA-Z])\s*\)\s*(?:[:.)-]\s*)?|"
    r"([a-zA-Z])\s*[:.)-]\s*)",
    re.S,
)


def _part_label(answer: str) -> tuple[re.Match[str] | None, str | None]:
    match = _LABEL.match(answer)
    if match is None:
        return None, None
    return match, (match.group(1) or match.group(2)).lower()


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
    match, _ = _part_label(answer)
    return answer[match.end():].strip() if match else answer.strip()


def map_separated_boxes(boxes: list[str], part_ids: list[str]) -> tuple[dict[str, str], list[str]]:
    answers: dict[str, str] = {}
    errors: list[str] = []
    parsed: list[tuple[str | None, str]] = []
    for index, box in enumerate(boxes):
        _, label = _part_label(box)
        parsed.append((label, strip_part_label(box)))
        if label in part_ids:
            if label not in answers:
                answers[label] = parsed[-1][1]
            else:
                errors.append(f"duplicate box for part {label}")
    # Only use positional fallback after preserving every explicit valid label.
    for index, (label, content) in enumerate(parsed):
        if label in part_ids or index >= len(part_ids):
            continue
        positional_label = part_ids[index]
        if positional_label not in answers:
            answers[positional_label] = content
            errors.append(f"box {index + 1} lacked a valid label; assigned by position")
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
