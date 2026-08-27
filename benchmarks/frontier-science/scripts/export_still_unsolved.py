#!/usr/bin/env python3
"""Export questions still unsolved after five closed-book and one tool-enabled attempt."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
FIVE_ROUND_ROOT = ROOT / "artifacts" / "gpt-5.6-sol-high-best-of-5"
TOOLS_ROOT = ROOT / "artifacts" / "gpt-5.6-sol-high-tools-on-five-round-failures"
SOURCE = FIVE_ROUND_ROOT / "failed_questions_with_all_answers.jsonl"
OUTPUT = TOOLS_ROOT / "still_unsolved_questions_with_all_answers.jsonl"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    source = {item["id"]: item for item in read_jsonl(SOURCE)}
    generations = {item["id"]: item for item in read_jsonl(TOOLS_ROOT / "generations.jsonl")}
    judgments = {item["id"]: item for item in read_jsonl(TOOLS_ROOT / "judgments.jsonl")}
    exported = []
    for eval_id in sorted(source, key=lambda key: (source[key]["track"], key)):
        judgment = judgments[eval_id]
        if judgment["success"]:
            continue
        generation = generations[eval_id]
        item = dict(source[eval_id])
        item["tool_enabled_attempt"] = {
            "response": generation["response"],
            "score": judgment["score"],
            "success": judgment["success"],
            "judge_reasoning": judgment["judgment"]["reasoning"],
            "tool_call_count": generation["tool_call_count"],
            "tool_types": generation["tool_types"],
            "tool_items": generation["tool_items"],
        }
        exported.append(item)
    with OUTPUT.open("w", encoding="utf-8") as handle:
        for item in exported:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"wrote {len(exported)} still-unsolved questions to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
