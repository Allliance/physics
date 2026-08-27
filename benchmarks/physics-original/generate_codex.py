"""Generate PHYSICS responses through the repository's Codex CLI API wrapper."""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.codex_cli import CodexLLM  # noqa: E402


SYSTEM_PROMPT = (
    "You are an AI expert specializing in answering advanced physics questions. "
    "Think step by step and provide solution and final answer. Provide the final "
    "answer at the end in Latex boxed format \\[\\boxed{}\\]. Example: "
    "\\[ \\boxed{ final_answer} \\]"
)
DEFAULT_INPUT = (
    Path(__file__).parent
    / "PHYSICS"
    / "PHYSICS-textonly"
    / "physics_textonly.jsonl"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "audit"
    / "all-responses"
    / "PHYSICS"
    / "gpt-5.6-sol-high.jsonl"
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_latest(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    return {row["id"]: row for row in read_jsonl(path)}


def generate_one(
    row: dict[str, Any],
    model: str,
    effort: str,
    timeout: float,
) -> dict[str, Any]:
    client = CodexLLM(
        model=model,
        model_reasoning_effort=effort,
        timeout=timeout,
        system_prompt=SYSTEM_PROMPT,
        strict_no_tools=True,
        max_tool_retries=3,
        max_exec_retries=2,
        exec_retry_delay=10.0,
    )
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        result = client.complete(row["questions"])
        return {
            "id": row["id"],
            "questions": row["questions"],
            "graphs": row.get("graphs"),
            "llm_answers": result.text,
            "model": model,
            "reasoning_effort": effort,
            "usage": result.usage,
            "attempts": result.attempts,
            "created_at": created_at,
            "generation_error": None,
        }
    except Exception as exc:  # Keep a resumable record of every failed item.
        return {
            "id": row["id"],
            "questions": row["questions"],
            "graphs": row.get("graphs"),
            "llm_answers": None,
            "model": model,
            "reasoning_effort": effort,
            "usage": None,
            "attempts": None,
            "created_at": created_at,
            "generation_error": f"{type(exc).__name__}: {exc}",
        }


def is_complete(row: dict[str, Any], model: str, effort: str) -> bool:
    return bool(row.get("llm_answers")) and (
        row.get("model") == model and row.get("reasoning_effort") == effort
    )


def canonicalize(
    path: Path,
    dataset: list[dict[str, Any]],
    latest: dict[str, dict[str, Any]],
) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        for source_row in dataset:
            result = latest.get(source_row["id"])
            if result is not None:
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    temp_path.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset = read_jsonl(args.input)
    if args.limit is not None:
        dataset = dataset[: args.limit]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    latest = load_latest(args.output)
    pending = [
        row
        for row in dataset
        if not is_complete(latest.get(row["id"], {}), args.model, args.reasoning_effort)
    ]
    print(
        f"dataset={len(dataset)} complete={len(dataset) - len(pending)} "
        f"pending={len(pending)} workers={args.workers}",
        flush=True,
    )

    with args.output.open("a", encoding="utf-8") as output_handle:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    generate_one,
                    row,
                    args.model,
                    args.reasoning_effort,
                    args.timeout,
                ): row["id"]
                for row in pending
            }
            completed = 0
            for future in as_completed(futures):
                result = future.result()
                latest[result["id"]] = result
                output_handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                output_handle.flush()
                completed += 1
                status = "ok" if result["llm_answers"] else "error"
                print(
                    f"[{completed}/{len(pending)}] {result['id']} {status}",
                    flush=True,
                )

    canonicalize(args.output, dataset, latest)
    failures = sum(not is_complete(row, args.model, args.reasoning_effort) for row in latest.values())
    print(f"wrote={args.output} failures={failures}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
