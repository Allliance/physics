#!/usr/bin/env python3
# /// script
# dependencies = ["pyarrow>=16"]
# ///
"""Build a deterministic manual-review set from separated evaluation artifacts."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parent.parent


def load_jsonl(path: Path) -> dict[str, dict]:
    records: dict[str, dict] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                records[record["key"]] = record
    return records


def review_rows(dataset: str, generator: str, judge: str) -> list[dict]:
    base = ROOT / "eval" / "artifacts" / dataset / "test" / "separated" / f"model_{generator}"
    responses = load_jsonl(base / "responses.jsonl")
    judgments = load_jsonl(base / f"judge_{judge}" / "judgments.jsonl")
    source_rows = {row["id"]: row for row in pq.read_table(ROOT / "final_datasets" / dataset / "test.parquet").to_pylist()}
    output = []
    for judgment in judgments.values():
        row = source_rows.get(judgment.get("id"))
        response = responses.get(judgment["key"])
        if row is None or response is None:
            continue
        parts = {}
        for part_id in judgment["part_ids"]:
            judged = judgment["parts"][part_id]
            parts[part_id] = {
                "extracted_answer": response.get("extracted_answers", {}).get(part_id, ""),
                "ground_truth": judged.get("ground_truth", ""),
                "judge_correct": judged.get("correct", False),
                "judge_reason": judged.get("reason", ""),
            }
        output.append(
            {
                "id": row["id"],
                "dataset": dataset,
                "split": "test",
                "mode": "separated",
                "generator": generator,
                "judge": judge,
                "score": judgment["score"],
                "question": row["question"],
                "evaluation_parts": parts,
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
    parser.add_argument("--per-dataset", type=int, default=5)
    parser.add_argument("--output", type=Path, default=ROOT / "inspection" / "reviews" / "gpt-5.5_separated_review.json")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    selected = []
    for dataset in ("Physics", "FrontierPhysics"):
        rows = review_rows(dataset, args.generator, args.judge)
        worst = sorted(rows, key=lambda row: (row["score"], row["id"]))[: args.per_dataset]
        worst_ids = {row["id"] for row in worst}
        pool = [row for row in rows if row["id"] not in worst_ids]
        random_rows = rng.sample(pool, args.per_dataset)
        for selection, group in (("worst", worst), ("random", random_rows)):
            for row in group:
                row["selection"] = selection
                selected.append(row)

    selected.sort(key=lambda row: ({"worst": 0, "random": 1}[row["selection"]], row["dataset"], row["score"], row["id"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(selected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(selected)} review samples to {args.output}")


if __name__ == "__main__":
    main()
