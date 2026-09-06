#!/usr/bin/env python3
# /// script
# dependencies = ["pyarrow>=16"]
# ///
"""Build inspection rows for the best GPT-5.5 attempt per hard-filtered problem."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.pipeline import _attempt_key, _key


def load_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                records[record["key"]] = record
    return records


def parse_ground_truths(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def judge_reason(judgment: dict[str, Any]) -> str:
    reason_lines = []
    parts = judgment.get("parts")
    if isinstance(parts, dict):
        for part_id in judgment.get("part_ids", []):
            part = parts.get(part_id, {})
            reason = str(part.get("reason", "")).strip()
            score = part.get("score")
            if reason:
                reason_lines.append(f"({part_id}) score {score}: {reason}")
    return "\n".join(reason_lines)


def part_scores(judgment: dict[str, Any]) -> dict[str, Any]:
    parts = judgment.get("parts")
    if not isinstance(parts, dict):
        return {}
    return {
        part_id: part.get("score")
        for part_id, part in parts.items()
        if isinstance(part, dict)
    }


def build_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    dataset = args.dataset.resolve()
    rows = pq.read_table(dataset).to_pylist()
    responses = load_jsonl(args.responses)
    judgments = load_jsonl(args.judgments)

    output = []
    for row_index, row in enumerate(rows):
        row_key = _key(dataset, row)
        attempts = []
        for attempt in range(1, args.repeat + 1):
            key = _attempt_key(row_key, attempt)
            response = responses.get(key)
            judgment = judgments.get(key)
            if response is None or judgment is None:
                raise ValueError(f"Missing attempt {attempt} for row {row_index} id={row.get('id')} key={key}")
            attempts.append(
                {
                    "repeat": attempt,
                    "key": key,
                    "score": judgment.get("score"),
                    "part_ids": judgment.get("part_ids", []),
                    "part_scores": part_scores(judgment),
                    "extracted_answer": response.get("extracted_answer", ""),
                    "generated_response": response.get("response", ""),
                    "format_errors": response.get("format_errors", []),
                    "judge_reason": judge_reason(judgment),
                    "judge_response": judgment.get("judge_response", ""),
                    "response_usage": response.get("usage", {}),
                    "judgment_usage": judgment.get("usage", {}),
                    "created_at": judgment.get("created_at"),
                }
            )

        best = max(
            attempts,
            key=lambda attempt: (
                -1.0 if attempt["score"] is None else float(attempt["score"]),
                -int(attempt["repeat"]),
            ),
        )
        best_judgment = judgments[best["key"]]
        ground_truths = parse_ground_truths(row.get("ground_truths"))
        judged_ground_truths = {
            part: ground_truths.get(part)
            for part in best_judgment.get("part_ids", [])
        }
        score = best["score"]
        score_label = "unscored" if score is None else f"score:{float(score):.3f}"
        source_dataset = str(row.get("dataset") or "Hardest")
        source_split = str(row.get("split") or "hardest_filtered")
        output.append(
            {
                "id": row.get("id", ""),
                "key": row_key,
                "best_attempt_key": best["key"],
                "source_file": row.get("source_file", ""),
                "dataset": "Hardest/hardest_filtered",
                "source_dataset": source_dataset,
                "source_split": source_split,
                "source_row_index": row_index,
                "mode": "merged",
                "generator": args.generator,
                "judge": args.judge,
                "score": score,
                "mean_at_4": sum(float(item["score"]) for item in attempts if item["score"] is not None) / len(attempts),
                "best_attempt": best["repeat"],
                "part_ids": best_judgment.get("part_ids", []),
                "selection": "best-of-4",
                "labels": [
                    "best-of-4",
                    "merged",
                    "Hardest/hardest_filtered",
                    f"best-attempt:{best['repeat']}",
                    score_label,
                    f"source:{source_dataset}",
                    f"split:{source_split}",
                ],
                "review_note": (
                    f"Best GPT-5.5 high merged attempt out of {args.repeat}; "
                    f"tie-breaker is earliest attempt. Best attempt: {best['repeat']}."
                ),
                "question": row.get("question", ""),
                "processed_question": row.get("question", ""),
                "original_question": (
                    row.get("original_question")
                    or row.get("unpartitioned_question")
                    or row.get("question", "")
                ),
                "solution": row.get("solution", ""),
                "evaluation_parts": {
                    f"best attempt {best['repeat']}": {
                        "extracted_answer": best.get("extracted_answer", ""),
                        "reference_title": "Final solution",
                        "reference_answer": row.get("solution", ""),
                        "ground_truth": json.dumps(judged_ground_truths, ensure_ascii=False, indent=2),
                        "cleaned_ground_truths": json.dumps(ground_truths, ensure_ascii=False, indent=2),
                        "judge_score": score,
                        "judge_correct": score == 1.0,
                        "judge_reason": best.get("judge_reason", ""),
                        "judge_raw_response": best_judgment.get("judge_response", ""),
                        "judge_usage": json.dumps(
                            {
                                "best_attempt": best["repeat"],
                                "best_attempt_key": best["key"],
                                "usage": best_judgment.get("usage", {}),
                                "judge_reasoning_effort": best_judgment.get("judge_reasoning_effort"),
                                "judge_max_tokens": best_judgment.get("judge_max_tokens"),
                                "created_at": best_judgment.get("created_at"),
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                    }
                },
                "format_errors": best.get("format_errors", []),
                "full_model_response": best.get("generated_response", ""),
                "evaluation_attempts": attempts,
            }
        )

    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=ROOT / "final_datasets" / "Hardest" / "hardest_filtered.parquet",
    )
    parser.add_argument(
        "--responses",
        type=Path,
        default=ROOT
        / "eval"
        / "artifacts"
        / "Hardest"
        / "hardest_filtered"
        / "merged"
        / "model_gpt-5.5_gen_4aaf5fd9c9"
        / "responses.jsonl",
    )
    parser.add_argument(
        "--judgments",
        type=Path,
        default=ROOT
        / "eval"
        / "artifacts"
        / "Hardest"
        / "hardest_filtered"
        / "merged"
        / "model_gpt-5.5_gen_4aaf5fd9c9"
        / "judge_gpt-5.5"
        / "judgments.jsonl",
    )
    parser.add_argument("--generator", default="gpt-5.5")
    parser.add_argument("--judge", default="gpt-5.5")
    parser.add_argument("--repeat", type=int, default=4)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "inspection" / "reviews" / "hardest_filtered_gpt55_best_of_4.json",
    )
    args = parser.parse_args()

    rows = build_rows(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} best-of-{args.repeat} review samples to {args.output}")


if __name__ == "__main__":
    main()
