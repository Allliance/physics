"""Rescore saved PRISM generations with the shared binary LLM judge."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from llm_judge.eval import (
    CodexJudge,
    JudgeClient,
    OpenAICompatibleJudge,
    RunConfig,
    parse_judgment,
)
from llm_judge.prompts import get_prompt


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _ground_truth(row: dict[str, Any]) -> dict[str, Any]:
    value = row["gts"]
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("gts must be a JSON object or an encoded JSON object")
    return value


def _row_id(row: dict[str, Any], index: int) -> str:
    """Return a stable ID even though verl's generation dump omits dataset UIDs."""
    if row.get("uid") is not None:
        return str(row["uid"])
    identity = {
        "index": index,
        "input": row.get("input"),
        "gts": row.get("gts"),
        "output": row.get("output"),
        "step": row.get("step"),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()[:20]
    return f"row-{index:06d}-{digest}"


def _judge(
    row: dict[str, Any], row_id: str, client: JudgeClient, config: RunConfig
) -> dict[str, Any]:
    started = time.monotonic()
    uid = row_id
    base = {
        "uid": uid,
        "step": row.get("step"),
        "run_id": config.run_id,
        "model": config.model,
        "reasoning_effort": config.reasoning_effort,
        "prompt_name": config.prompt_name,
        "prompt_fingerprint": config.prompt_fingerprint,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        truth = _ground_truth(row)
        prompt_row = {
            "problem_statement": truth["problem"],
            "reference_solution": truth["reference_answer"],
            "model_response": row["output"],
        }
        system_prompt, user_prompt = get_prompt(config.prompt_name).render(prompt_row)
        completion = client.complete(system_prompt, user_prompt)
        grade, reason = parse_judgment(completion.text)
        return {
            **base,
            "status": "completed",
            "grade": grade,
            "reason": reason,
            "judge_response": completion.text,
            "usage": completion.usage,
            "latency_seconds": round(time.monotonic() - started, 3),
        }
    except Exception as error:
        return {
            **base,
            "status": "error",
            "error": f"{type(error).__name__}: {error}",
            "latency_seconds": round(time.monotonic() - started, 3),
        }


def _latest_records(path: Path, run_id: str) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    records: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("run_id") != run_id:
            raise ValueError(f"{path}:{line_number} belongs to a different run configuration")
        records[str(record["uid"])] = record
    return records


def evaluate(
    rows: list[dict[str, Any]],
    output: Path,
    client: JudgeClient,
    config: RunConfig,
    workers: int,
) -> list[dict[str, Any]]:
    records = _latest_records(output, config.run_id)
    indexed_rows = [(row, _row_id(row, index)) for index, row in enumerate(rows)]
    pending = [
        (row, row_id)
        for row, row_id in indexed_rows
        if records.get(row_id, {}).get("status") != "completed"
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as handle:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_judge, row, row_id, client, config): row_id
                for row, row_id in pending
            }
            for index, future in enumerate(as_completed(futures), start=1):
                record = future.result()
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                records[record["uid"]] = record
                print(f"[{index}/{len(pending)}] {record['uid']}: {record['status']}", flush=True)
    return [records[row_id] for _row, row_id in indexed_rows if row_id in records]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--backend", choices=("codex", "openai"), default="codex")
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--base-url")
    parser.add_argument("--api-key", default="EMPTY")
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--top-p", type=float)
    parser.add_argument("--extra-body", type=json.loads)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--errors-as-zero",
        dest="errors_as_zero",
        action="store_true",
        default=True,
        help="Use fail-closed binary-reward semantics: judge errors score zero.",
    )
    parser.add_argument(
        "--strict-errors",
        dest="errors_as_zero",
        action="store_false",
        help="Exit nonzero when any judge request fails so a later run can retry it.",
    )
    args = parser.parse_args()

    if args.workers < 1:
        raise ValueError("workers must be at least 1")
    if args.overwrite:
        args.output.unlink(missing_ok=True)
    rows = _read_jsonl(args.input)
    if not rows:
        raise ValueError("input contains no generations")

    prompt = get_prompt("default")
    config = RunConfig(
        backend=args.backend,
        model=args.model,
        prompt_name=prompt.name,
        prompt_fingerprint=prompt.fingerprint,
        response_format="json-schema",
        reasoning_effort=args.reasoning_effort if args.backend == "codex" else None,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
        extra_body=args.extra_body,
        base_url=args.base_url.rstrip("/") if args.base_url else None,
    )
    if args.backend == "codex":
        unsupported = any(
            value is not None
            for value in (args.base_url, args.max_tokens, args.temperature, args.top_p, args.extra_body)
        )
        if unsupported:
            raise ValueError("Codex backend does not accept OpenAI sampling arguments")
        client: JudgeClient = CodexJudge(
            model=args.model,
            timeout=args.timeout,
            response_format="json-schema",
            reasoning_effort=args.reasoning_effort,
        )
    else:
        if not args.base_url:
            raise ValueError("OpenAI backend requires --base-url")
        client = OpenAICompatibleJudge(
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
            timeout=args.timeout,
            response_format="json-schema",
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            top_p=args.top_p,
            extra_body=args.extra_body,
        )
    judgments = evaluate(rows, args.output, client, config, args.workers)

    completed = [row for row in judgments if row.get("status") == "completed"]
    correct = sum(row["grade"] for row in completed)
    errors = len(rows) - len(completed)
    summary = {
        "input": str(args.input),
        "output": str(args.output),
        "config": asdict(config),
        "num_rows": len(rows),
        "num_completed": len(completed),
        "num_correct": correct,
        "num_incorrect": len(completed) - correct,
        "num_judge_errors": errors,
        "binary_accuracy": correct / len(completed) if completed else None,
        "binary_reward_mean": correct / len(rows),
        "judge_error_policy": "zero" if args.errors_as_zero else "retry_required",
    }
    summary_path = args.output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if errors and not args.errors_as_zero:
        raise RuntimeError(f"binary evaluation had {errors} judge error(s); rerun to resume")


if __name__ == "__main__":
    main()
