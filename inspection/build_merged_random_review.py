#!/usr/bin/env python3
# /// script
# dependencies = ["pyarrow>=16"]
# ///
"""Build random merged-mode evaluation samples for the inspection tool."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.pipeline import _key


def load_jsonl(path: Path) -> dict[str, dict]:
    records: dict[str, dict] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                records[record["key"]] = record
    return records


def parse_ground_truths(value) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def judge_reason(judgment: dict) -> str:
    reason_lines = []
    parts = judgment.get("parts")
    if isinstance(parts, dict):
        for part in judgment.get("part_ids", []):
            part_result = parts.get(part, {})
            reason = str(part_result.get("reason", "")).strip()
            if reason:
                reason_lines.append(f"({part}) {reason}")
    return "\n".join(reason_lines)


def review_rows(dataset: str, generator: str, judge: str, rng: random.Random, count: int) -> list[dict]:
    dataset_path = ROOT / "final_datasets" / dataset / "test.parquet"
    artifact = (
        ROOT
        / "eval"
        / "artifacts"
        / dataset
        / "test"
        / "merged"
        / f"model_{generator}_gen_772970d6d2"
    )
    responses = load_jsonl(artifact / "responses.jsonl")
    judgments = load_jsonl(artifact / f"judge_{judge}" / "judgments.jsonl")
    source_rows = {
        _key(dataset_path, row): row
        for row in pq.read_table(dataset_path).to_pylist()
    }

    available_keys = sorted(set(source_rows) & set(responses) & set(judgments))
    if len(available_keys) < count:
        raise ValueError(f"{dataset} has only {len(available_keys)} complete merged samples")

    selected_keys = rng.sample(available_keys, count)
    output = []
    for rank, key in enumerate(selected_keys, start=1):
        row = source_rows[key]
        response = responses[key]
        judgment = judgments[key]
        ground_truths = parse_ground_truths(row.get("ground_truths"))
        judged_ground_truths = {part: ground_truths.get(part) for part in judgment.get("part_ids", [])}
        score = judgment.get("score")
        judge_usage = {
            "raw_response": judgment.get("judge_response", ""),
            "correct_parts": judgment.get("correct", []),
            "usage": judgment.get("usage", {}),
            "judge_reasoning_effort": judgment.get("judge_reasoning_effort"),
            "judge_max_tokens": judgment.get("judge_max_tokens"),
            "created_at": judgment.get("created_at"),
        }
        output.append(
            {
                "id": row.get("id", ""),
                "key": key,
                "source_file": row.get("source_file", ""),
                "dataset": dataset,
                "split": "test",
                "mode": "merged",
                "generator": generator,
                "judge": judge,
                "score": score,
                "part_ids": judgment.get("part_ids", []),
                "selection": "random",
                "random_rank": rank,
                "labels": ["random", "merged", dataset, f"score:{score}"],
                "question": row.get("question", ""),
                "solution": row.get("solution", ""),
                "evaluation_parts": {
                    "merged": {
                        "extracted_answer": response.get("extracted_answer", ""),
                        "reference_title": "Final solution",
                        "reference_answer": row.get("solution", ""),
                        "ground_truth": json.dumps(judged_ground_truths, ensure_ascii=False, indent=2),
                        "cleaned_ground_truths": json.dumps(ground_truths, ensure_ascii=False, indent=2),
                        "judge_score": score,
                        "judge_correct": score == 1.0,
                        "judge_reason": judge_reason(judgment),
                        "judge_raw_response": judgment.get("judge_response", ""),
                        "judge_usage": json.dumps(judge_usage, ensure_ascii=False, indent=2),
                    }
                },
                "format_errors": response.get("format_errors", []),
                "full_model_response": response.get("response", ""),
            }
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generator", default="gpt-5.5")
    parser.add_argument("--judge", default="gpt-5.5")
    parser.add_argument("--seed", type=int, default=55)
    parser.add_argument("--per-dataset", type=int, default=10)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "inspection" / "reviews" / "gpt-5.5_merged_random_review.json",
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)
    selected = []
    for dataset in ("Physics", "FrontierPhysics"):
        selected.extend(review_rows(dataset, args.generator, args.judge, rng, args.per_dataset))

    selected.sort(key=lambda row: (row["dataset"], row["random_rank"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(selected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(selected)} merged review samples to {args.output}")


if __name__ == "__main__":
    main()
