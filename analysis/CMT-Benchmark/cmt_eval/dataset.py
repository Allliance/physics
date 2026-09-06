"""Validate CMT rows and keep references separate from prediction inputs."""

import json
from pathlib import Path


def load_dataset(path: Path) -> tuple[list[dict], dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        rows = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {error.msg}") from error
    else:
        rows = json.loads(text)
    if not isinstance(rows, list) or not rows:
        raise ValueError("CMT dataset must be a nonempty JSON list or JSONL file of objects.")
    questions, answers = [], {}
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"CMT row {position} must be an object.")
        index = row.get("index")
        if type(index) is not int or index < 0:
            raise ValueError(f"CMT row {position} must have a nonnegative integer index.")
        qid = str(index)
        if qid in answers:
            raise ValueError(f"Duplicate CMT index: {index}")
        for field in ["prompt", "solution", "type"]:
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"CMT index {index} requires a nonempty {field} string.")
        # Audit notes, solutions, parameters, and other metadata never reach predictors.
        questions.append({"id": qid, "question": row["prompt"], "category": row["type"]})
        answers[qid] = row["solution"]
    return questions, answers


def select_questions(questions: list[dict], *, category: str = "all",
                     requested_ids: list[str] | None = None,
                     excluded_ids: list[str] | None = None,
                     max_samples: int | None = None) -> list[dict]:
    if category.casefold() != "all":
        questions = [q for q in questions if q["category"].casefold() == category.casefold()]
    if requested_ids is not None:
        wanted = set(requested_ids)
        missing = wanted - {q["id"] for q in questions}
        if missing:
            raise ValueError(f"Requested IDs not found in the category: {sorted(missing)}")
        questions = [q for q in questions if q["id"] in wanted]
    excluded = set(excluded_ids or [])
    questions = [q for q in questions if q["id"] not in excluded]
    return questions if max_samples is None else questions[:max_samples]


def read_ids(path: Path | None, option: str) -> list[str] | None:
    if path is None:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(
        (type(qid) is int and qid >= 0) or
        (isinstance(qid, str) and qid.isascii() and qid.isdecimal())
        for qid in value
    ):
        raise ValueError(f"{option} must contain a JSON list of nonnegative integer IDs or digit strings.")
    return [str(int(qid)) for qid in value]
