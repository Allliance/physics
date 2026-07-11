"""Generation, durable caching, judging, and result aggregation."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .llm import LLM
from .parsing import detect_part_ids, extract_boxes, map_separated_boxes, parse_json_object
from .prompts import (
    MERGED_GENERATION_SYSTEM, MERGED_JUDGE_SYSTEM, SEPARATED_GENERATION_SYSTEM,
    SEPARATED_JUDGE_SYSTEM, generation_prompt, merged_judge_prompt, separated_judge_prompt,
)

MERGED_SCHEMA = {
    "type": "object", "properties": {"correct": {"type": "array", "items": {"type": "string"}}},
    "required": ["correct"], "additionalProperties": False,
}
SEPARATED_SCHEMA = {
    "type": "object",
    "properties": {"correct": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["correct", "reason"], "additionalProperties": False,
}


def read_rows(path: Path) -> list[dict[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("Parquet support requires pyarrow: uv run --with pyarrow python -m eval ...") from exc
    return pq.read_table(path).to_pylist()


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def load_ground_truths(row: dict[str, Any]) -> dict[str, str]:
    if "ground_truths" not in row or row["ground_truths"] is None:
        raise ValueError(f"Row {row.get('id')!r} has no ground_truths value")
    supplied = _json_value(row["ground_truths"])
    if not isinstance(supplied, dict):
        raise ValueError(f"Row {row.get('id')!r} ground_truths must be a JSON object")
    return {str(part): str(answer) for part, answer in supplied.items()}


def resolve_ground_truth(row: dict[str, Any], parts: list[str]) -> tuple[dict[str, str], str]:
    supplied = load_ground_truths(row)
    missing = [part for part in parts if part not in supplied]
    if missing:
        raise ValueError(f"Row {row.get('id')!r} ground_truths is missing parts: {missing}")
    return {part: str(supplied[part]) for part in parts}, "ground_truths"


def _key(dataset: Path, row: dict[str, Any]) -> str:
    identity = f"{dataset.resolve()}\0{row.get('id')}\0{row.get('question')}"
    return hashlib.sha256(identity.encode()).hexdigest()[:20]


def _load_jsonl(path: Path, key: str = "key") -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text().splitlines():
        if line.strip():
            item = json.loads(line)
            result[item[key]] = item
    return result


def _append(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()


@dataclass
class RunConfig:
    mode: str
    generator_name: str
    judge_name: str
    limit: int | None = None
    overwrite: bool = False
    max_workers: int = 32


def model_artifact_dir(root: Path, dataset: Path, config: RunConfig) -> Path:
    model = re.sub(r"[^A-Za-z0-9_.-]+", "_", config.generator_name)
    return root / dataset.parent.name / dataset.stem / config.mode / f"model_{model}"


def artifact_dir(root: Path, dataset: Path, config: RunConfig) -> Path:
    judge = re.sub(r"[^A-Za-z0-9_.-]+", "_", config.judge_name)
    return model_artifact_dir(root, dataset, config) / f"judge_{judge}"


def run(dataset: Path, output_root: Path, config: RunConfig, generator: LLM, judge: LLM) -> Path:
    if config.mode not in {"merged", "separated"}:
        raise ValueError("mode must be merged or separated")
    rows = read_rows(dataset)
    if config.limit is not None:
        rows = rows[:config.limit]
    model_out = model_artifact_dir(output_root, dataset, config)
    out = artifact_dir(output_root, dataset, config)
    model_out.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    responses_path, judgments_path = model_out / "responses.jsonl", out / "judgments.jsonl"
    if config.overwrite:
        responses_path.unlink(missing_ok=True)
        judgments_path.unlink(missing_ok=True)
    responses, judgments = _load_jsonl(responses_path), _load_jsonl(judgments_path)
    gen_system = MERGED_GENERATION_SYSTEM if config.mode == "merged" else SEPARATED_GENERATION_SYSTEM

    write_lock = threading.Lock()

    def process_row(row: dict[str, Any]) -> None:
        key = _key(dataset, row)
        truths = load_ground_truths(row)
        parts = detect_part_ids(truths)
        if key not in responses:
            completion = generator.complete(generation_prompt(row["question"]), system_prompt=gen_system)
            boxes = extract_boxes(completion.text)
            record = {
                "key": key, "dataset": str(dataset), "id": row.get("id"), "part_ids": parts,
                "response": completion.text, "boxes": boxes, "usage": completion.usage,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if config.mode == "merged":
                record["extracted_answer"] = boxes[-1] if len(boxes) == 1 else ""
                record["format_errors"] = [] if len(boxes) == 1 else [f"expected 1 box, found {len(boxes)}"]
            else:
                record["extracted_answers"], record["format_errors"] = map_separated_boxes(boxes, parts)
            with write_lock:
                _append(responses_path, record)
                responses[key] = record

        response = responses[key]
        if key in judgments:
            return
        if config.mode == "merged":
            completion = judge.complete(
                merged_judge_prompt(row["question"], str(row.get("solution") or ""),
                                    response.get("extracted_answer", ""), parts),
                system_prompt=MERGED_JUDGE_SYSTEM, schema=MERGED_SCHEMA,
            )
            parsed = parse_json_object(completion.text)
            correct = [p for p in parsed.get("correct", []) if p in parts]
            judgment = {"key": key, "id": row.get("id"), "part_ids": parts, "correct": correct,
                        "score": len(set(correct)) / len(parts), "judge_response": completion.text,
                        "usage": completion.usage}
        else:
            truths, provenance = resolve_ground_truth(row, parts)
            per_part, correct = {}, []
            for part in parts:
                completion = judge.complete(
                    separated_judge_prompt(row["question"], part, truths[part],
                                           response.get("extracted_answers", {}).get(part, "")),
                    system_prompt=SEPARATED_JUDGE_SYSTEM, schema=SEPARATED_SCHEMA,
                )
                parsed = parse_json_object(completion.text)
                is_correct = parsed.get("correct") is True
                if is_correct:
                    correct.append(part)
                per_part[part] = {"correct": is_correct, "reason": str(parsed.get("reason", "")),
                                  "judge_response": completion.text, "usage": completion.usage,
                                  "ground_truth": truths[part]}
            judgment = {"key": key, "id": row.get("id"), "part_ids": parts, "correct": correct,
                        "score": len(correct) / len(parts), "ground_truth_source": provenance,
                        "parts": per_part}
        judgment["created_at"] = datetime.now(timezone.utc).isoformat()
        with write_lock:
            _append(judgments_path, judgment)
            judgments[key] = judgment

    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        list(executor.map(process_row, rows))

    selected = [judgments[_key(dataset, row)] for row in rows if _key(dataset, row) in judgments]
    summary = {
        "dataset": str(dataset), "mode": config.mode, "generator": config.generator_name,
        "judge": config.judge_name, "num_rows": len(selected),
        "mean_score": sum(x["score"] for x in selected) / len(selected) if selected else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out / "run_config.json").write_text(json.dumps(asdict(config), indent=2) + "\n")
    return out
