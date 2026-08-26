#!/usr/bin/env python3
"""Audit native-EED false negatives among unsolved PHYBench attempts."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


BENCHMARK_ROOT = Path(__file__).resolve().parent
REPO_ROOT = BENCHMARK_ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from utils.codex_cli import CodexLLM  # noqa: E402


SYSTEM_PROMPT = """You are auditing a deterministic symbolic grader for a difficult physics benchmark.
Compare each candidate FINAL ANSWER with the official reference answer, using the official solution to
interpret notation and conventions. Ignore derivation quality: assess only whether the final expressions
are mathematically and physically equivalent for the variables defined in the problem.

Be exacting. Harmless rearrangement, an explicitly equivalent definition, presentation wrappers, or an
omitted left-hand-side label can be equivalent. A sign error, reciprocal, missing factor, different
variable, extra assumption, unjustified absolute value, wrong component, or only a special case is not
equivalent. Do not infer that a reference is wrong unless the supplied solution clearly establishes it.
Use UNCERTAIN when equivalence cannot be established reliably from the supplied material."""

SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": ["EQUIVALENT", "NOT_EQUIVALENT", "UNCERTAIN"],
                    },
                    "reason": {"type": "string"},
                },
                "required": ["candidate_id", "verdict", "reason"],
                "additionalProperties": False,
            },
        },
        "overall_assessment": {
            "type": "string",
            "enum": ["GRADER_CORRECT", "GRADER_FALSE_NEGATIVE", "UNCERTAIN"],
        },
        "notes": {"type": "string"},
    },
    "required": ["candidate_reviews", "overall_assessment", "notes"],
    "additionalProperties": False,
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def unique_candidates(attempts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[int, str]]:
    by_answer: dict[str, str] = {}
    candidates = []
    round_mapping = {}
    for attempt in attempts:
        answer = attempt["final_answer"].strip()
        candidate_id = by_answer.get(answer)
        if candidate_id is None:
            candidate_id = f"C{len(candidates) + 1}"
            by_answer[answer] = candidate_id
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "final_answer": attempt["final_answer"],
                    "normalized_final_answer": attempt.get("normalized_final_answer", ""),
                    "eed_score": attempt["eed_score"],
                }
            )
        round_mapping[int(attempt["round"])] = candidate_id
    return candidates, round_mapping


def review_one(row: dict[str, Any], model: str, effort: str, timeout: float, schema_path: Path) -> dict[str, Any]:
    candidates, round_mapping = unique_candidates(row["attempts"])
    candidate_text = "\n\n".join(
        f"{candidate['candidate_id']} (native EED {candidate['eed_score']}):\n{candidate['final_answer']}"
        for candidate in candidates
    )
    prompt = f"""Problem ID: {row['id']}
Category: {row['tag']}

PROBLEM:
{row['question']}

OFFICIAL REFERENCE ANSWER:
{row['reference_answer']}

OFFICIAL SOLUTION:
{row.get('solution', '')}

CANDIDATE FINAL ANSWERS (duplicate attempts have been collapsed):
{candidate_text}

Return exactly one review for every candidate ID. Set GRADER_FALSE_NEGATIVE if at least one candidate
is equivalent to the reference despite native EED < 100. Set GRADER_CORRECT only if every candidate is
not equivalent. Otherwise use UNCERTAIN."""
    result = CodexLLM(
        model=model,
        model_reasoning_effort=effort,
        timeout=timeout,
    ).complete(prompt, system_prompt=SYSTEM_PROMPT, output_schema=schema_path)
    parsed = json.loads(result.text)
    expected_ids = {candidate["candidate_id"] for candidate in candidates}
    actual_ids = {item["candidate_id"] for item in parsed["candidate_reviews"]}
    if actual_ids != expected_ids or len(parsed["candidate_reviews"]) != len(candidates):
        raise ValueError(f"Candidate review mismatch for {row['id']}: expected {expected_ids}, got {actual_ids}")
    return {
        "id": row["id"],
        "tag": row["tag"],
        "candidates": candidates,
        "round_mapping": {str(key): value for key, value in round_mapping.items()},
        **parsed,
        "review_usage": result.usage,
        "review_wrapper_attempts": result.attempts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--input",
        type=Path,
        default=BENCHMARK_ROOT / "artifacts" / "gpt-5.6-sol-high-best-of-5" / "unsolved_questions_with_answers.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=BENCHMARK_ROOT / "artifacts" / "gpt-5.6-sol-high-best-of-5" / "equivalence_review.jsonl",
    )
    args = parser.parse_args()
    rows = read_jsonl(args.input)
    dataset_rows = json.loads(
        (BENCHMARK_ROOT / "data" / "PHYBench-fullques_v1.json").read_text(
            encoding="utf-8"
        )
    )
    dataset_by_id = {str(item["id"]): item for item in dataset_rows}
    for row in rows:
        source = dataset_by_id[row["id"]]
        row.setdefault("question", source.get("content", ""))
        row.setdefault("reference_answer", source.get("answer", ""))
        row["solution"] = source.get("solution", "")
    if args.limit is not None:
        rows = rows[: args.limit]
    schema_path = args.output.with_suffix(".schema.json")
    schema_path.write_text(json.dumps(SCHEMA), encoding="utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    existing = {item["id"] for item in read_jsonl(args.output)}
    pending = [row for row in rows if row["id"] not in existing]
    lock = threading.Lock()
    print(f"reviewing {len(pending)} of {len(rows)} unsolved questions", flush=True)
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {
            pool.submit(
                review_one, row, args.model, args.reasoning_effort, args.timeout, schema_path
            ): row["id"]
            for row in pending
        }
        for future in as_completed(futures):
            item = future.result()
            with lock, args.output.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
                handle.flush()
            print(f"reviewed {item['id']}: {item['overall_assessment']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
