#!/usr/bin/env python3
"""Aggregate four corrected PHYBench HLE-adapted Kimi attempts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()

    summaries = []
    for attempt in range(1, 5):
        path = args.run / f"attempt-{attempt}" / "summary.json"
        if path.exists():
            summaries.append(json.loads(path.read_text()))

    report = {
        "model": "moonshotai/Kimi-K3",
        "reasoning_effort": "max",
        "judge_model": "gpt-5.6-sol",
        "judge_reasoning_effort": "high",
        "benchmark": "phybench",
        "split": "frozen-gemini-corrected",
        "evaluator": "HLE-adapted physics equivalence; merged binary score",
        "attempts_complete": sum(bool(row.get("complete")) for row in summaries),
        "complete": False,
    }
    if len(summaries) == 4 and all(row.get("complete") for row in summaries):
        per_attempt = [
            {row["id"]: bool(row["correct"]) for row in summary["per_question"]}
            for summary in summaries
        ]
        ids = [row["id"] for row in summaries[0]["per_question"]]
        if any(set(values) != set(ids) for values in per_attempt):
            raise ValueError("Attempt question IDs differ")
        grades = {qid: [int(values[qid]) for values in per_attempt] for qid in ids}
        report.update(
            questions=len(ids),
            mean_at_4=sum(map(sum, grades.values())) / (4 * len(ids)),
            pass_at_4=sum(any(values) for values in grades.values()) / len(ids),
            per_question=grades,
            complete=True,
        )

    atomic_json(args.run / "summary.json", report)
    print(json.dumps({key: value for key, value in report.items() if key != "per_question"}, indent=2))
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
