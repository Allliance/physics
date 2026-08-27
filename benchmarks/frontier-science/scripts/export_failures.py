#!/usr/bin/env python3
"""Export questions unsolved after sequential retries with every attempted answer."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

BENCHMARK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCHMARK_ROOT))

import evaluate


ROOT = BENCHMARK_ROOT
ARTIFACT_ROOT = ROOT / "artifacts" / "gpt-5.6-sol-high-best-of-5"
OUTPUT = ARTIFACT_ROOT / "failed_questions_with_all_answers.jsonl"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    summary = json.loads((ARTIFACT_ROOT / "summary.json").read_text(encoding="utf-8"))
    failed_ids = {
        eval_id
        for track in evaluate.TRACKS
        for eval_id in summary["tracks"][track]["unsolved_ids"]
    }
    rows = {
        row["_eval_id"]: (track, row)
        for track in evaluate.TRACKS
        for row in evaluate.load_physics(ROOT / "data", track)
    }
    generations: dict[tuple[int, str], dict[str, Any]] = {}
    judgments: dict[tuple[int, str], dict[str, Any]] = {}
    for round_number in range(1, 6):
        round_dir = ARTIFACT_ROOT / f"round-{round_number}"
        generations.update({
            (round_number, item["id"]): item
            for item in read_jsonl(round_dir / "generations.jsonl")
        })
        judgments.update({
            (round_number, item["id"]): item
            for item in read_jsonl(round_dir / "judgments.jsonl")
        })

    exported = []
    for eval_id in sorted(failed_ids, key=lambda key: (rows[key][0], key)):
        track, row = rows[eval_id]
        attempts = []
        for round_number in range(1, 6):
            generation = generations[(round_number, eval_id)]
            judgment = judgments[(round_number, eval_id)]
            attempts.append({
                "round": round_number,
                "response": generation["response"],
                "score": judgment["score"],
                "success": judgment["success"],
                "judge_reasoning": judgment["judgment"]["reasoning"],
            })
        exported.append({
            "id": eval_id,
            "task_group_id": row["task_group_id"],
            "track": track,
            "subject": row["subject"],
            "problem": row["problem"],
            "reference_answer" if track == "olympiad" else "rubric": row["answer"],
            "attempts": attempts,
        })

    with OUTPUT.open("w", encoding="utf-8") as handle:
        for item in exported:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"wrote {len(exported)} failed questions to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
