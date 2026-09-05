"""Incrementally judge GPT cleanup generations with the binary LLM judge.

The generator appends rows over many hours.  This worker repeatedly snapshots
that append-only file, judges newly available rows, and resumes from its own
JSONL output.  Rows from the already audited seed run can be excluded because
their benchmark-validity decisions are reused directly by the dataset builder.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from llm_judge.eval import OpenAICompatibleJudge, RunConfig
from llm_judge.prompts import get_prompt
from rlvr.evaluate_binary import evaluate


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _judge_rows(
    sample_by_id: dict[str, dict[str, Any]],
    generations: list[dict[str, Any]],
    excluded_ids: set[str],
) -> list[dict[str, Any]]:
    rows = []
    for generation in generations:
        item_id = str(generation["id"])
        if item_id in excluded_ids:
            continue
        sample = sample_by_id[item_id]
        truth = {
            "benchmark": "ugphysics",
            "problem_id": item_id,
            "problem": sample["problem"],
            "reference_answer": sample["solution"],
        }
        rows.append(
            {
                "uid": item_id,
                "step": "dataset_cleanup",
                "output": generation["completion"],
                "gts": json.dumps(truth, ensure_ascii=False),
            }
        )
    return rows


def _write_summary(
    path: Path,
    config: RunConfig,
    expected_rows: int,
    available_generations: int,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    latest = {str(row["uid"]): row for row in records}
    completed = [row for row in latest.values() if row.get("status") == "completed"]
    correct = sum(int(row["grade"]) for row in completed)
    errors = [row for row in latest.values() if row.get("status") != "completed"]
    summary = {
        "expected_rows": expected_rows,
        "available_generations": available_generations,
        "unique_judgments": len(latest),
        "completed_judgments": len(completed),
        "judge_errors": len(errors),
        "accepted": correct,
        "acceptance_rate": correct / len(completed) if completed else None,
        "config": asdict(config),
    }
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--generations", type=Path, required=True)
    parser.add_argument("--exclude-sample", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-total", type=int, default=5520)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", default="Qwen/Qwen3.5-27B")
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--poll-seconds", type=float, default=15.0)
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args()

    sample = _read_jsonl(args.sample)
    if len(sample) != args.expected_total:
        raise ValueError(
            f"sample has {len(sample)} rows, expected {args.expected_total}"
        )
    sample_by_id = {str(row["_eval_id"]): row for row in sample}
    if len(sample_by_id) != len(sample):
        raise ValueError("sample contains duplicate _eval_id values")
    excluded_ids = {
        str(row["_eval_id"])
        for row in _read_jsonl(args.exclude_sample)
    } if args.exclude_sample else set()
    expected_rows = args.expected_total - len(excluded_ids)

    prompt = get_prompt("default")
    extra_body = {
        "chat_template_kwargs": {"enable_thinking": True},
        "thinking_token_budget": 4096,
        "top_k": 20,
        "min_p": 0.0,
    }
    config = RunConfig(
        backend="openai",
        model=args.model,
        prompt_name=prompt.name,
        prompt_fingerprint=prompt.fingerprint,
        response_format="json-schema",
        max_tokens=8192,
        temperature=0.6,
        top_p=0.95,
        extra_body=extra_body,
        base_url=args.base_url.rstrip("/"),
    )
    client = OpenAICompatibleJudge(
        model=args.model,
        base_url=args.base_url.rstrip("/"),
        api_key="EMPTY",
        timeout=args.timeout,
        response_format="json-schema",
        max_tokens=8192,
        temperature=0.6,
        top_p=0.95,
        extra_body=extra_body,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    summary_path = args.output.with_suffix(".summary.json")

    while True:
        generations = _read_jsonl(args.generations)
        generation_by_id = {str(row["id"]): row for row in generations}
        if len(generation_by_id) != len(generations):
            raise ValueError("generations contain duplicate IDs")
        unknown = set(generation_by_id) - set(sample_by_id)
        if unknown:
            raise ValueError(f"generation IDs missing from sample: {sorted(unknown)[:5]}")
        rows = _judge_rows(
            sample_by_id,
            list(generation_by_id.values()),
            excluded_ids,
        )
        if rows:
            evaluate(rows, args.output, client, config, args.workers)
        records = _read_jsonl(args.output)
        summary = _write_summary(
            summary_path,
            config,
            expected_rows,
            len(rows),
            records,
        )
        print(json.dumps(summary), flush=True)
        if (
            len(rows) == expected_rows
            and summary["completed_judgments"] == expected_rows
        ):
            return
        time.sleep(max(1.0, args.poll_seconds))


if __name__ == "__main__":
    main()
