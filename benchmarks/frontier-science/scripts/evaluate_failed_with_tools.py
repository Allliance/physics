#!/usr/bin/env python3
"""Evaluate the five-round failures once more with Codex tools enabled."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BENCHMARK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCHMARK_ROOT))

import evaluate
from utils.codex_cli import CodexLLM


ROOT = BENCHMARK_ROOT
SOURCE = ROOT / "artifacts" / "gpt-5.6-sol-high-best-of-5" / "failed_questions_with_all_answers.jsonl"
DEFAULT_OUTPUT = ROOT / "artifacts" / "gpt-5.6-sol-high-tools-on-five-round-failures"
TOOL_TYPES = {"command_execution", "file_change", "mcp_tool_call", "web_search"}
SYSTEM_PROMPT = """Solve the supplied science problem rigorously and give a self-contained final response.
You have access to tools, including shell/code execution and web search. Use any available tools that
help you solve or verify the problem. Obey all output instructions in the problem."""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def tool_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    items = [event.get("item") or {} for event in events]
    used_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        if item.get("type") not in TOOL_TYPES:
            continue
        key = str(item.get("id") or f"event-{index}")
        used_by_id[key] = item
    used = list(used_by_id.values())
    return {
        "tool_call_count": len(used),
        "tool_types": sorted({item["type"] for item in used}),
        "tool_items": used,
    }


def normalize_tool_record(item: dict[str, Any]) -> dict[str, Any]:
    """Collapse the started/completed events retained by older cached runs."""
    unique: dict[str, dict[str, Any]] = {}
    for index, tool_item in enumerate(item.get("tool_items", [])):
        key = str(tool_item.get("id") or f"event-{index}")
        unique[key] = tool_item
    normalized = dict(item)
    normalized["tool_items"] = list(unique.values())
    normalized["tool_call_count"] = len(unique)
    normalized["tool_types"] = sorted({tool_item["type"] for tool_item in unique.values()})
    return normalized


def generate(row: dict[str, Any], model: str, effort: str, timeout: float) -> dict[str, Any]:
    client = CodexLLM(
        model=model,
        model_reasoning_effort=effort,
        timeout=timeout,
        strict_no_tools=False,
        web_search="live",
        sandbox_mode="workspace-write",
        env_inherit="none",
    )
    result = client.complete(row["problem"], system_prompt=SYSTEM_PROMPT)
    return {
        "id": row["id"],
        "task_group_id": row["task_group_id"],
        "track": row["track"],
        "subject": "physics",
        "response": result.text,
        "usage": result.usage,
        **tool_summary(result.events),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--judge-model", default="gpt-5.6-sol")
    parser.add_argument("--judge-reasoning-effort", default="high")
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    config = evaluate.Config(
        args.model, args.reasoning_effort, args.judge_model,
        args.judge_reasoning_effort, args.timeout,
    )
    failed = read_jsonl(SOURCE)
    source_by_id = {item["id"]: item for item in failed}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    generation_path = args.output_dir / "generations.jsonl"
    judgment_path = args.output_dir / "judgments.jsonl"
    generations = [normalize_tool_record(item) for item in read_jsonl(generation_path)]
    generation_by_id = {item["id"]: item for item in generations}
    lock = threading.Lock()
    missing = [item for item in failed if item["id"] not in generation_by_id]
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {
            pool.submit(generate, item, args.model, args.reasoning_effort, args.timeout): item["id"]
            for item in missing
        }
        for future in as_completed(futures):
            item = future.result()
            generation_by_id[item["id"]] = item
            evaluate._write_jsonl(generation_path, item, lock)
            print(f"generated {item['track']} {item['id']} with {item['tool_call_count']} tool calls", flush=True)

    judgments = read_jsonl(judgment_path)
    judgment_ids = {item["id"] for item in judgments}
    pending = [generation_by_id[item["id"]] for item in failed if item["id"] not in judgment_ids]
    judge_rows = {
        item["id"]: {
            "problem": item["problem"],
            "answer": item.get("reference_answer", item.get("rubric")),
        }
        for item in failed
    }
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {
            pool.submit(evaluate.judge_one, judge_rows[item["id"]], item, config): item["id"]
            for item in pending
        }
        for future in as_completed(futures):
            item = future.result()
            evaluate._write_jsonl(judgment_path, item, lock)
            print(f"judged {item['track']} {item['id']}: {item['score']}", flush=True)

    generations = [normalize_tool_record(item) for item in read_jsonl(generation_path)]
    with generation_path.open("w", encoding="utf-8") as handle:
        for item in generations:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    judgments = read_jsonl(judgment_path)
    summary: dict[str, Any] = {
        "benchmark": "openai/frontierscience physics five-round failures with tools",
        "dataset_revision": evaluate.DATASET_REVISION,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "tool_policy": {
            "shell_and_files": True,
            "web_search": "live",
            "workspace": "isolated temporary directory",
            "benchmark_files_visible": False,
            "judge_tools": False,
        },
        "question_count": len(failed),
        "responses_using_tools": sum(item["tool_call_count"] > 0 for item in generations),
        "total_tool_calls": sum(item["tool_call_count"] for item in generations),
        "tool_call_counts_by_type": {
            tool_type: sum(
                tool_item["type"] == tool_type
                for item in generations
                for tool_item in item["tool_items"]
            )
            for tool_type in sorted(TOOL_TYPES)
        },
        "responses_using_each_tool_type": {
            tool_type: sum(tool_type in item["tool_types"] for item in generations)
            for tool_type in sorted(TOOL_TYPES)
        },
        "tracks": {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    for track in evaluate.TRACKS:
        track_judgments = [item for item in judgments if item["track"] == track]
        successes = sum(item["success"] for item in track_judgments)
        summary["tracks"][track] = {
            "evaluated": len(track_judgments),
            "successes": successes,
            "accuracy_on_prior_failures": successes / len(track_judgments) if track_judgments else None,
            "successful_ids": sorted(item["id"] for item in track_judgments if item["success"]),
        }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
