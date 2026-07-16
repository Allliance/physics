#!/usr/bin/env python3
# /// script
# dependencies = ["pyarrow>=16"]
# ///
"""Build a curated merged-mode FrontierPhysics false-positive review set.

This is intentionally conservative. Cleaned-data omissions, null ground-truth
parts, and part relabeling are not false positives in merged mode because the
judge is supposed to score only retained ``ground_truths`` parts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.pipeline import _key


CANDIDATES: list[dict[str, str]] = []


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


def find_row(rows: list[dict], source_file: str, row_id: str) -> dict:
    matches = [row for row in rows if row.get("source_file") == source_file and row.get("id") == row_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one row for {source_file} / {row_id}, found {len(matches)}")
    return matches[0]


def build_review_rows(args: argparse.Namespace) -> list[dict]:
    dataset = args.dataset.resolve()
    rows = pq.read_table(dataset).to_pylist()
    responses = load_jsonl(args.responses)
    judgments = load_jsonl(args.judgments)

    output = []
    for index, candidate in enumerate(CANDIDATES, start=1):
        row = find_row(rows, candidate["source_file"], candidate["id"])
        key = _key(dataset, row)
        response = responses.get(key)
        judgment = judgments.get(key)
        if response is None or judgment is None:
            raise ValueError(f"Missing artifacts for {candidate['source_file']} / {candidate['id']} ({key})")

        ground_truths = parse_ground_truths(row.get("ground_truths"))
        judged_ground_truths = {part: ground_truths.get(part) for part in judgment.get("part_ids", [])}
        score = float(judgment.get("score", 0.0))
        judge_raw_response = judgment.get("judge_response", "")
        judge_usage = {
            "raw_response": judge_raw_response,
            "correct_parts": judgment.get("correct", []),
            "usage": judgment.get("usage", {}),
            "judge_reasoning_effort": judgment.get("judge_reasoning_effort"),
            "judge_max_tokens": judgment.get("judge_max_tokens"),
            "created_at": judgment.get("created_at"),
        }
        judge_reason = judgment.get("reason") or judgment.get("judge_reason")
        if not judge_reason and isinstance(judgment.get("parts"), dict):
            reason_lines = []
            for part in judgment.get("part_ids", []):
                part_result = judgment["parts"].get(part, {})
                reason = str(part_result.get("reason", "")).strip()
                if reason:
                    reason_lines.append(f"({part}) {reason}")
            judge_reason = "\n".join(reason_lines)
        if not judge_reason:
            judge_reason = (
                "No textual judge rationale was stored in the merged artifact; "
                "only the raw correct-parts JSON decision is available."
            )
        output.append(
            {
                "id": row["id"],
                "key": key,
                "source_file": row.get("source_file", ""),
                "dataset": "FrontierPhysics",
                "split": "test",
                "mode": "merged",
                "generator": args.generator,
                "judge": args.judge,
                "score": score,
                "part_ids": judgment.get("part_ids", []),
                "selection": candidate["selection"],
                "confidence": candidate["confidence"],
                "review_note": candidate["note"],
                "labels": [
                    candidate["selection"],
                    f"confidence:{candidate['confidence']}",
                    "merged",
                    "FrontierPhysics",
                ],
                "question": row.get("question", ""),
                "solution": row.get("solution", ""),
                "evaluation_parts": {
                    "merged": {
                        "extracted_answer": response.get("extracted_answer", ""),
                        "reference_title": "Final solution",
                        "reference_answer": row.get("solution", ""),
                        "ground_truth": json.dumps(judged_ground_truths, ensure_ascii=False, indent=2),
                        "cleaned_ground_truths": json.dumps(ground_truths, ensure_ascii=False, indent=2),
                        "judge_correct": score == 1.0,
                        "judge_reason": judge_reason,
                        "judge_raw_response": judge_raw_response,
                        "judge_usage": json.dumps(judge_usage, ensure_ascii=False, indent=2),
                    }
                },
                "format_errors": response.get("format_errors", []),
                "full_model_response": response.get("response", ""),
                "candidate_rank": index,
            }
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=ROOT / "final_datasets" / "FrontierPhysics" / "test.parquet",
    )
    parser.add_argument(
        "--responses",
        type=Path,
        default=ROOT
        / "eval"
        / "artifacts"
        / "FrontierPhysics"
        / "test"
        / "merged"
        / "model_gpt-5.5_gen_772970d6d2"
        / "responses.jsonl",
    )
    parser.add_argument(
        "--judgments",
        type=Path,
        default=ROOT
        / "eval"
        / "artifacts"
        / "FrontierPhysics"
        / "test"
        / "merged"
        / "model_gpt-5.5_gen_772970d6d2"
        / "judge_gpt-5.5"
        / "judgments.jsonl",
    )
    parser.add_argument("--generator", default="gpt-5.5")
    parser.add_argument("--judge", default="gpt-5.5")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "inspection" / "reviews" / "frontier_gpt55_high_merged_false_positive_candidates.json",
    )
    args = parser.parse_args()

    rows = build_review_rows(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} merged review candidates to {args.output}")


if __name__ == "__main__":
    main()
