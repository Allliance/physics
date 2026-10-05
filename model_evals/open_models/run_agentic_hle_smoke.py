#!/usr/bin/env python3
"""Run a small, resumable HLE tool-use evaluation through OpenRouter."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval.backends import make_judge, validate_judgment
from eval.storage import atomic_json, fingerprint
from utils.codex_cli import CodexLLM, validate_codex_result


DEFAULT_SOURCE = (
    ROOT
    / "model_evals/kimi/runs/kimi-k3-max-no-tools-20260917/hle-corrected/hle"
)
DEFAULT_IDS = (
    "66e89ebe7361982cbfbc5952",  # composite-fermion flux attachment
    "6735bafad86155d1e57160e7",  # two-centre 2s overlap integral
    "678dadfaa2acdbbe2a403cb7",  # IAU constellation boundary lookup
)
SYSTEM_PROMPT = """You are solving a difficult physics evaluation problem.

Use the available tools actively when useful. You may search the web for primary
sources and use shell commands, Python, symbolic algebra, and scratch files for
calculations. Cross-check exact numerical or bibliographic claims.

Do not inspect the local filesystem for benchmark datasets, previous model
answers, reference solutions, judgments, or evaluation artifacts. Only inspect
files that you create yourself in the current scratch workspace.

Give a self-contained solution and follow the question's requested output
format. Put the final answer in a single \\boxed{} LaTeX environment.
"""


def read_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def append_error(path: Path, qid: str, stage: str, exc: BaseException) -> None:
    record = {
        "id": qid,
        "stage": stage,
        "error": f"{type(exc).__name__}: {exc}",
        "time": datetime.now(timezone.utc).isoformat(),
    }
    with path.open("a") as handle:
        handle.write(json.dumps(record) + "\n")


def record_partial(output: Path, qid: str, exc: BaseException) -> None:
    partial = getattr(exc, "partial_result", None)
    if partial is None:
        return
    partials = read_json(output / "partial_generations.json", {})
    partials[qid] = partial
    atomic_json(output / "partial_generations.json", partials)


def require_four_failures(source: Path, ids: tuple[str, ...]) -> None:
    for attempt in range(1, 5):
        judgments = read_json(source / f"attempt-{attempt}/judgments.json", {})
        invalid = [
            qid
            for qid in ids
            if judgments.get(qid, {}).get("judgment", {}).get("correct") != "no"
        ]
        if invalid:
            raise ValueError(
                f"Selected IDs were not all incorrect in attempt {attempt}: {invalid}"
            )


def selected_rows(source: Path, ids: tuple[str, ...]) -> list[dict]:
    rows = read_json(source / "attempt-1/dataset.json")
    by_id = {row["id"]: row for row in rows}
    missing = [qid for qid in ids if qid not in by_id]
    if missing:
        raise ValueError(f"Selected IDs missing from HLE dataset: {missing}")
    return [by_id[qid] for qid in ids]


def agent_client(args) -> CodexLLM:
    requested_model = f"{args.model}@preset/{args.preset}"
    return CodexLLM(
        model=requested_model,
        model_reasoning_effort=args.reasoning_effort,
        timeout=args.timeout,
        system_prompt=SYSTEM_PROMPT,
        strict_no_tools=False,
        max_exec_retries=2,
        web_search="disabled",
        sandbox_mode="workspace-write",
        env_inherit="none",
        reasoning_summary="concise",
        capture_workspace=True,
        config_overrides=[
            'model_provider="openrouter"',
            'model_providers.openrouter.name="OpenRouter"',
            'model_providers.openrouter.base_url="https://openrouter.ai/api/v1"',
            'model_providers.openrouter.env_key="OPENROUTER_API_KEY"',
            'model_providers.openrouter.wire_api="responses"',
            "model_providers.openrouter.supports_websockets=false",
            "model_context_window=1048576",
            "model_auto_compact_token_limit=900000",
        ],
    )


def generate_one(client: CodexLLM, row: dict, requested_model: str) -> dict:
    result = client.complete(row["question"])
    validate_codex_result(result)
    tool_events = []
    for event in result.events:
        item = event.get("item") or {}
        if item.get("type") in {
            "command_execution",
            "file_change",
            "mcp_tool_call",
            "web_search",
        }:
            tool_events.append(item)
    return {
        "response": result.text,
        "usage": result.usage,
        "requested_model": requested_model,
        "actual_model": None,
        "attempts": result.attempts,
        "tool_events": tool_events,
        "events": result.events,
        "workspace_files": result.workspace_files or {},
        "refused": False,
    }


def generate_native(args, row: dict) -> dict:
    from utils.openai_compatible import generate_with_tools

    return generate_with_tools(
        row["question"], system_prompt=SYSTEM_PROMPT,
        reasoning_effort=args.reasoning_effort,
        max_output_tokens=args.max_output_tokens,
        timeout=args.timeout, max_tool_turns=args.max_tool_turns,
        command_timeout=args.command_timeout, web_search=True,
        codex_bin=args.codex_bin,
    )


def judge_client_args(args):
    return SimpleNamespace(
        judge_model="gpt-5.6-sol",
        judge_reasoning_effort="high",
        judge_max_output_tokens=32768,
        model="kimi-k3",
        reasoning_effort=args.reasoning_effort,
        codex_bin=args.codex_bin,
        timeout=args.timeout,
        fable_model=None,
    )


def summarize(rows: list[dict], predictions: dict, judgments: dict) -> dict:
    per_question = []
    for row in rows:
        qid = row["id"]
        judgment = judgments.get(qid, {}).get("judgment")
        events = predictions.get(qid, {}).get("tool_events", [])
        event_types = {
            event if isinstance(event, str) else event.get("type") or event.get("name")
            for event in events
        }
        per_question.append(
            {
                "id": qid,
                "generated": qid in predictions,
                "judged": judgment is not None,
                "correct": judgment.get("correct") == "yes" if judgment else None,
                "tool_event_types": sorted(value for value in event_types if value),
            }
        )
    judged = [row for row in per_question if row["judged"]]
    return {
        "complete": len(judged) == len(rows),
        "questions": len(rows),
        "generated": len(predictions),
        "judged": len(judged),
        "correct": sum(row["correct"] for row in judged),
        "accuracy": (
            sum(row["correct"] for row in judged) / len(rows) if len(judged) == len(rows) else None
        ),
        "per_question": per_question,
    }


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--ids", nargs="+", default=list(DEFAULT_IDS))
    p.add_argument("--model", default="moonshotai/kimi-k3")
    p.add_argument("--preset", default="agentic-web")
    p.add_argument("--harness", choices=("native-openrouter", "codex"),
                   default="native-openrouter")
    p.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    p.add_argument("--reasoning-effort",
                   choices=("low", "medium", "high", "xhigh", "max"), default="max")
    p.add_argument("--max-output-tokens", type=int, default=384000)
    p.add_argument("--max-tool-turns", type=int, default=20)
    p.add_argument("--command-timeout", type=float, default=120)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--timeout", type=float, default=3600)
    p.add_argument("--codex-bin", default="codex")
    return p


def main() -> int:
    args = parser().parse_args()
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise RuntimeError("OPENROUTER_API_KEY is required")
    if min(args.workers, args.timeout, args.max_output_tokens,
           args.max_tool_turns, args.command_timeout) <= 0:
        raise ValueError("workers, timeouts, token budget, and tool turns must be positive")
    ids = tuple(dict.fromkeys(args.ids))
    require_four_failures(args.source, ids)
    rows = selected_rows(args.source, ids)
    requested_model = (f"{args.model}@preset/{args.preset}"
                       if args.harness == "codex" else args.model)
    if args.harness == "native-openrouter":
        os.environ["OPENAI_COMPAT_BASE_URL"] = args.base_url
        os.environ["OPENAI_COMPAT_MODEL"] = args.model

    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": 2,
        "dataset": "hle-corrected",
        "selection": "incorrect in all four saved Kimi K3 max no-tool attempts",
        "source": str(args.source.resolve()),
        "ids": list(ids),
        "model": args.model,
        "requested_model": requested_model,
        "base_url": args.base_url if args.harness == "native-openrouter" else None,
        "reasoning_effort": args.reasoning_effort,
        "harness": "codex exec" if args.harness == "codex" else "native OpenRouter tool loop",
        "tools": ["Codex-sandboxed run_command", "openrouter:web_search"],
        "openrouter_preset": args.preset if args.harness == "codex" else None,
        "sandbox": ("workspace-write" if args.harness == "codex" else
                    "Codex eval-tool profile: scratch write, minimal read, no network"),
        "max_output_tokens": args.max_output_tokens,
        "max_tool_turns": args.max_tool_turns,
        "request_attempts_per_turn": 1,
        "judge_model": "gpt-5.6-sol",
        "judge_reasoning_effort": "high",
    }
    existing_manifest = read_json(args.output / "manifest.json")
    if existing_manifest is not None and existing_manifest != manifest:
        raise ValueError("Output manifest differs; choose a new output directory")
    atomic_json(args.output / "manifest.json", manifest)
    atomic_json(args.output / "dataset.json", rows)

    predictions = read_json(args.output / "predictions.json", {})
    client = agent_client(args) if args.harness == "codex" else None
    pending = [row for row in rows if row["id"] not in predictions]
    with ThreadPoolExecutor(max_workers=min(args.workers, len(pending) or 1)) as pool:
        futures = {
            pool.submit(
                generate_one, client, row, requested_model
            ) if client is not None else pool.submit(generate_native, args, row): row["id"]
            for row in pending
        }
        for future in as_completed(futures):
            qid = futures[future]
            try:
                predictions[qid] = future.result()
                atomic_json(args.output / "predictions.json", predictions)
                print(f"generated {qid}", flush=True)
            except Exception as exc:
                record_partial(args.output, qid, exc)
                append_error(args.output / "errors.jsonl", qid, "generate", exc)
                print(f"generation failed {qid}: {exc}", file=sys.stderr, flush=True)

    judgments = read_json(args.output / "judgments.json", {})
    judge = make_judge(judge_client_args(args))
    pending_judgments = [
        row for row in rows if row["id"] in predictions and row["id"] not in judgments
    ]

    def judge_one(row: dict) -> dict:
        prediction = predictions[row["id"]]
        result = judge(row, prediction)
        validate_judgment(result["judgment"])
        return {**result, "prediction_sha256": fingerprint(prediction)}

    with ThreadPoolExecutor(max_workers=min(args.workers, len(pending_judgments) or 1)) as pool:
        futures = {pool.submit(judge_one, row): row["id"] for row in pending_judgments}
        for future in as_completed(futures):
            qid = futures[future]
            try:
                judgments[qid] = future.result()
                atomic_json(args.output / "judgments.json", judgments)
                verdict = judgments[qid]["judgment"]["correct"]
                print(f"judged {qid}: {verdict}", flush=True)
            except Exception as exc:
                append_error(args.output / "errors.jsonl", qid, "judge", exc)
                print(f"judgment failed {qid}: {exc}", file=sys.stderr, flush=True)

    summary = summarize(rows, predictions, judgments)
    atomic_json(args.output / "summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if summary["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
