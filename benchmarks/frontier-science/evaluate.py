#!/usr/bin/env python3
"""Run the public FrontierScience benchmark with Codex CLI models."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from utils.codex_cli import CodexLLM  # noqa: E402


DATASET_REVISION = "25ed67db7da8f4591484e764008ff585544f5a30"
DATASET_URL = f"https://huggingface.co/datasets/openai/frontierscience/resolve/{DATASET_REVISION}/{{track}}/test.jsonl"
TRACKS = ("olympiad", "research")

GENERATION_SYSTEM = (
    "Solve the supplied science problem yourself. Give a rigorous, self-contained answer and obey "
    "all output instructions in the problem. Do not use tools, files, web search, or external context."
)

OLYMPIAD_JUDGE_SYSTEM = """You are grading an attempted answer to a science olympiad problem. You will be given the
problem, attempted answer, and reference answer. Evaluate the solution against the provided
reference solution, ensuring it is complete and matches the reference solution. Pay close
attention to detail and grade it strictly, but fairly.
The reference answer is either a single number or expression in latex formatting, a chemical
formula, a compound name, or a phrase referring to a specific name, entity, or method.
Mark the attempted answer as correct if it fully matches the reference answer or is otherwise
equivalent (e.g., an equivalent algebraic expression, a numerical number within 1 decimal
place rounding of the reference answer (e.g., 6.69 ≈ 6.7), an equivalent name for a compound/formula,
equivalent when accounting for units, etc.). Mark it as incorrect if it is not equivalent to the reference answer."""

RESEARCH_JUDGE_SYSTEM = """You are grading a science exam.
You will be given the problem, attempted answer, and a rubric to grade the answer. The rubric
will total up to 10 points.
Evaluate the attempted answer against the provided rubric. Pay close attention to detail and
grade it strictly, but fairly. Only evaluate against the rubric, as you yourself should not make
any judgements (e.g., even if you think the answer is correct but rubric is wrong, you should
treat the rubric as the gold standard). Return the absolute total number of points earned (it can
be a decimal based on the rubric)."""

OLYMPIAD_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "verdict": {"type": "string", "enum": ["CORRECT", "INCORRECT"]},
    },
    "required": ["reasoning", "verdict"],
    "additionalProperties": False,
}
RESEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "score": {"type": "number", "minimum": 0, "maximum": 10},
    },
    "required": ["reasoning", "score"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Config:
    model: str
    reasoning_effort: str
    judge_model: str
    judge_reasoning_effort: str
    timeout: float


def _write_jsonl(path: Path, row: dict[str, Any], lock: threading.Lock) -> None:
    with lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def download_data(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for track in TRACKS:
        target = data_dir / f"{track}.jsonl"
        if target.exists():
            continue
        with urlopen(DATASET_URL.format(track=track), timeout=60) as response:
            payload = response.read()
        target.write_bytes(payload)


def load_physics(data_dir: Path, track: str) -> list[dict[str, Any]]:
    rows = _read_jsonl(data_dir / f"{track}.jsonl")
    physics = [row for row in rows if row.get("subject") == "physics"]
    occurrences: dict[str, int] = {}
    for row in physics:
        task_id = row["task_group_id"]
        occurrences[task_id] = occurrences.get(task_id, 0) + 1
        occurrence = occurrences[task_id]
        row["_eval_id"] = task_id if occurrence == 1 else f"{task_id}:duplicate:{occurrence}"
    return physics


def _client(model: str, effort: str, timeout: float) -> CodexLLM:
    return CodexLLM(model=model, model_reasoning_effort=effort, timeout=timeout)


def generate_one(row: dict[str, Any], track: str, config: Config) -> dict[str, Any]:
    result = _client(config.model, config.reasoning_effort, config.timeout).complete(
        row["problem"], system_prompt=GENERATION_SYSTEM
    )
    return {
        "id": row["_eval_id"], "task_group_id": row["task_group_id"],
        "track": track, "subject": "physics",
        "response": result.text, "usage": result.usage, "attempts": result.attempts,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def judge_one(row: dict[str, Any], generation: dict[str, Any], config: Config) -> dict[str, Any]:
    track = generation["track"]
    if track == "olympiad":
        prompt = (
            f"The problem: {row['problem']}\n\n***\nThe reference answer: {row['answer']}\n\n***\n"
            f"The attempted answer: {generation['response']}\n\n***\n"
            "First, think step-by-step about whether the attempted answer matches the reference answer."
        )
        schema, system = OLYMPIAD_SCHEMA, OLYMPIAD_JUDGE_SYSTEM
    else:
        prompt = (
            f"The problem: {row['problem']}\n\n***\nThe rubric: {row['answer']}\n\n***\n"
            f"The attempted answer: {generation['response']}\n\n***\n"
            "First, think step-by-step about each rubric item. Explain your reasoning for each rubric item, then tally the points."
        )
        schema, system = RESEARCH_SCHEMA, RESEARCH_JUDGE_SYSTEM
    schema_path = Path(__file__).resolve().parent / f".{track}-judge-schema.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    result = _client(config.judge_model, config.judge_reasoning_effort, config.timeout).complete(
        prompt, system_prompt=system, output_schema=schema_path
    )
    parsed = json.loads(result.text)
    score = (1.0 if parsed["verdict"] == "CORRECT" else 0.0) if track == "olympiad" else float(parsed["score"])
    return {
        "id": generation["id"], "track": track, "score": score,
        "success": score >= (1.0 if track == "olympiad" else 7.0),
        "judgment": parsed, "usage": result.usage, "attempts": result.attempts,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def summarize(generations: list[dict[str, Any]], judgments: list[dict[str, Any]], config: Config) -> dict[str, Any]:
    tracks: dict[str, Any] = {}
    for track in TRACKS:
        scores = [j["score"] for j in judgments if j["track"] == track]
        successes = sum(j["success"] for j in judgments if j["track"] == track)
        expected = 50 if track == "olympiad" else 20
        tracks[track] = {
            "completed": len(scores), "expected": expected,
            "successes": successes,
            "accuracy": successes / len(scores) if scores else None,
            "mean_rubric_score": (sum(scores) / len(scores) if scores else None) if track == "research" else None,
        }
    return {
        "benchmark": "openai/frontierscience physics", "dataset_revision": DATASET_REVISION,
        "config": asdict(config), "generation_count": len(generations), "tracks": tracks,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track", choices=["all", *TRACKS], default="all")
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--judge-model", default="gpt-5.6-sol")
    parser.add_argument("--judge-reasoning-effort", default="high")
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "artifacts" / "gpt-5.6-sol-high")
    args = parser.parse_args()
    config = Config(args.model, args.reasoning_effort, args.judge_model, args.judge_reasoning_effort, args.timeout)
    root = Path(__file__).resolve().parent
    download_data(root / "data")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    generation_path, judgment_path = args.output_dir / "generations.jsonl", args.output_dir / "judgments.jsonl"
    lock = threading.Lock()
    generations = _read_jsonl(generation_path)
    judgments = _read_jsonl(judgment_path)
    generation_by_id = {item["id"]: item for item in generations}
    judgment_ids = {item["id"] for item in judgments}
    tracks = TRACKS if args.track == "all" else (args.track,)
    rows = [(track, row) for track in tracks for row in load_physics(root / "data", track)]
    if args.limit is not None:
        rows = rows[:args.limit]
    row_by_id = {row["_eval_id"]: row for _, row in rows}

    missing_generation = [(track, row) for track, row in rows if row["_eval_id"] not in generation_by_id]
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {pool.submit(generate_one, row, track, config): row["_eval_id"] for track, row in missing_generation}
        for future in as_completed(futures):
            item = future.result()
            generation_by_id[item["id"]] = item
            _write_jsonl(generation_path, item, lock)
            print(f"generated {item['track']} {item['id']}", flush=True)

    missing_judgments = [generation_by_id[row["_eval_id"]] for _, row in rows if row["_eval_id"] not in judgment_ids]
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {pool.submit(judge_one, row_by_id[item["id"]], item, config): item["id"] for item in missing_judgments}
        for future in as_completed(futures):
            item = future.result()
            judgments.append(item)
            _write_jsonl(judgment_path, item, lock)
            print(f"judged {item['track']} {item['id']}: {item['score']}", flush=True)

    generations = _read_jsonl(generation_path)
    judgments = _read_jsonl(judgment_path)
    summary = summarize(generations, judgments, config)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
