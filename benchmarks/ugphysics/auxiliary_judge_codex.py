#!/usr/bin/env python3
"""Apply UGPhysics's auxiliary equivalence judge to automatic-score failures."""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BENCHMARK_ROOT = Path(__file__).resolve().parent
REPO_ROOT = BENCHMARK_ROOT.parents[1]
CODE_ROOT = BENCHMARK_ROOT / "codes"
sys.path.insert(0, str(REPO_ROOT))
from utils.codex_cli import CodexLLM  # noqa: E402

sys.path.insert(0, str(CODE_ROOT))
for module_name in ("utils.codex_cli", "utils"):
    sys.modules.pop(module_name, None)
from judge import Judger  # noqa: E402


JUDGE_PROMPT_PATH = BENCHMARK_ROOT / "data" / "judge_prompt.txt"
DEFAULT_RUN_DIR = BENCHMARK_ROOT / "artifacts" / "gpt-5.6-sol-high-random-100"
SYSTEM_PROMPT = (
    "Act as the requested physics equivalence judge. Follow the supplied grading "
    "instructions exactly. Do not use tools, files, web search, or external context."
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def append_jsonl(path: Path, item: dict[str, Any], lock: threading.Lock) -> None:
    with lock, path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        handle.flush()


def extracted_answers(judger: Judger, text: str) -> list[str]:
    answer = judger.extract_ans(text)
    if not answer:
        return []
    return judger.trans_plus_minus_sign(judger.split_by_comma(answer))


def build_prompt(
    template: str, row: dict[str, Any], generation: dict[str, Any], judger: Judger
) -> str | None:
    student_answers = extracted_answers(judger, generation["completion"])
    if not student_answers:
        return None
    reference_answers = extracted_answers(judger, row["answers"])
    return (
        template.replace("{{problem}}", row["problem"])
        .replace("{{RS}}", row["solution"])
        .replace("{{RA}}", ", ".join(reference_answers))
        .replace("{{SS}}", generation["completion"])
        .replace("{{SA}}", ", ".join(student_answers))
    )


def parse_verdict(report: str) -> bool:
    match = re.search(
        r"##\s*Equivalence Judgement\s*\n+\s*\**(TRUE|FALSE)\**",
        report,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError(f"Could not parse auxiliary verdict from report: {report[:300]!r}")
    return match.group(1).upper() == "TRUE"


def judge_one(
    row: dict[str, Any],
    generation: dict[str, Any],
    template: str,
    model: str,
    effort: str,
    timeout: float,
) -> dict[str, Any]:
    prompt = build_prompt(template, row, generation, Judger(strict_extract=True))
    if prompt is None:
        return {
            "id": row["_eval_id"],
            "correct": False,
            "report": None,
            "reason": "student answer extraction error",
            "usage": None,
            "wrapper_attempts": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    result = CodexLLM(
        model=model, model_reasoning_effort=effort, timeout=timeout
    ).complete(prompt, system_prompt=SYSTEM_PROMPT)
    return {
        "id": row["_eval_id"],
        "correct": parse_verdict(result.text),
        "report": result.text,
        "reason": "auxiliary equivalence judge",
        "usage": result.usage,
        "wrapper_attempts": result.attempts,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--judge-model", default="gpt-5.6-sol")
    parser.add_argument("--judge-reasoning-effort", default="high")
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args()

    sample = read_jsonl(args.run_dir / "sample.jsonl")
    rows = {row["_eval_id"]: row for row in sample}
    generations = {item["id"]: item for item in read_jsonl(args.run_dir / "generations.jsonl")}
    automatic = {item["id"]: item for item in read_jsonl(args.run_dir / "scores.jsonl")}
    if set(rows) != set(generations) or set(rows) != set(automatic):
        raise ValueError("Sample, generations, and automatic scores do not contain identical IDs")

    output_path = args.run_dir / "auxiliary_judgments.jsonl"
    auxiliary = {item["id"]: item for item in read_jsonl(output_path)}
    pending = [
        rows[item_id]
        for item_id, item in automatic.items()
        if not item["correct"] and item_id not in auxiliary
    ]
    template = JUDGE_PROMPT_PATH.read_text(encoding="utf-8")
    lock = threading.Lock()
    print(f"automatic passes: {sum(x['correct'] for x in automatic.values())}; auxiliary pending: {len(pending)}", flush=True)
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {
            pool.submit(
                judge_one,
                row,
                generations[row["_eval_id"]],
                template,
                args.judge_model,
                args.judge_reasoning_effort,
                args.timeout,
            ): row["_eval_id"]
            for row in pending
        }
        for future in as_completed(futures):
            item = future.result()
            auxiliary[item["id"]] = item
            append_jsonl(output_path, item, lock)
            print(f"auxiliary {item['id']}: {item['correct']} ({len(auxiliary)}/70)", flush=True)

    automatic_passes = sum(item["correct"] for item in automatic.values())
    auxiliary_passes = sum(item["correct"] for item in auxiliary.values())
    final_correct = automatic_passes + auxiliary_passes
    grouped: dict[str, list[bool]] = defaultdict(list)
    for row in sample:
        item_id = row["_eval_id"]
        is_correct = bool(automatic[item_id]["correct"] or auxiliary.get(item_id, {}).get("correct"))
        grouped[f"language/{row['language']}"].append(is_correct)
        grouped[f"subject/{row['subject']}"].append(is_correct)
    summary = json.loads((args.run_dir / "summary.json").read_text(encoding="utf-8"))
    summary["auxiliary_judge"] = {
        "model": args.judge_model,
        "reasoning_effort": args.judge_reasoning_effort,
        "prompt": "Released UGPhysics data/judge_prompt.txt",
        "judged_automatic_failures": len(auxiliary),
        "accepted": auxiliary_passes,
    }
    summary["final_scoring"] = (
        "UGPhysics auto_judge first; released auxiliary equivalence prompt on automatic failures."
    )
    summary["final_correct"] = final_correct
    summary["final_accuracy"] = final_correct / len(sample)
    summary["final_breakdown"] = {
        key: {
            "total": len(values),
            "correct": sum(values),
            "accuracy": sum(values) / len(values),
        }
        for key, values in sorted(grouped.items())
    }
    summary["updated_at"] = datetime.now(timezone.utc).isoformat()
    summary_path = args.run_dir / "summary_with_auxiliary_judge.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
