#!/usr/bin/env python3
"""Filter prepared parquet datasets with an OpenAI-compatible LLM judge."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from openai import OpenAI


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.codex_cli import CodexLLM

DEFAULT_INPUT_DIR = REPO_ROOT / "original_datasets" / "prepared" / "FrontierPhysics"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "filtered_datasets" / "prepared" / "FrontierPhysics"
DEFAULT_DECISIONS_DIR = REPO_ROOT / "data" / "filter" / "decisions" / "FrontierPhysics"
DEFAULT_PROMPT = Path(__file__).resolve().parent / "prompts" / "final_answerable.txt"
FINAL_ANSWERABLE_VERDICTS = {
    "fully_final_answerable",
    "partial_final_answerable",
    "non_final_answerable",
}
KEEP_VERDICTS = {"fully_final_answerable", "partial_final_answerable"}
LEGACY_LABEL_TO_VERDICT = {
    "final_answerable": "fully_final_answerable",
    "descriptive": "non_final_answerable",
    "keep": "fully_final_answerable",
    "drop": "non_final_answerable",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Filter parquet dataset splits using an OpenAI-compatible LLM judge."
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--decisions-dir", type=Path, default=DEFAULT_DECISIONS_DIR)
    parser.add_argument("--prompt-file", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument(
        "--judge-backend",
        choices=("openai", "codex-cli"),
        default="openai",
        help="Backend used for judging each record.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of records to judge in parallel.",
    )
    parser.add_argument(
        "--splits",
        nargs="*",
        help="Parquet split filenames to process. Defaults to every *.parquet in input-dir.",
    )
    parser.add_argument("--model")
    parser.add_argument("--model-reasoning-effort", default=os.getenv("CODEX_LLM_REASONING_EFFORT"))
    parser.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL"))
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY"))
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=300)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--codex-bin", default=os.getenv("CODEX_BIN", "codex"))
    parser.add_argument("--max-tool-retries", type=int, default=3)
    parser.add_argument("--max-exec-retries", type=int, default=6)
    parser.add_argument("--exec-retry-delay", type=float, default=10.0)
    parser.add_argument(
        "--output-mode",
        choices=("kept", "verdict-subsets", "both"),
        default="kept",
        help="Write one kept parquet, verdict-specific subset parquets, or both.",
    )
    parser.add_argument("--limit", type=int, help="Only process the first N rows per split.")
    parser.add_argument(
        "--on-error",
        choices=("fail", "keep", "drop"),
        default="fail",
        help="What to do if the judge call or response parsing fails.",
    )
    parser.add_argument(
        "--no-json-mode",
        action="store_true",
        help="Do not request OpenAI JSON mode. Useful for providers that do not support it.",
    )
    return parser.parse_args()


def load_prompt(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def list_split_files(input_dir: Path, splits: list[str] | None) -> list[Path]:
    if splits:
        files = [input_dir / split for split in splits]
    else:
        files = sorted(input_dir.glob("*.parquet"))
    missing = [str(path) for path in files if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing split file(s): " + ", ".join(missing))
    if not files:
        raise FileNotFoundError(f"No parquet files found in {input_dir}")
    return files


def compact_record(row: dict[str, Any], index: int) -> dict[str, Any]:
    """Keep judge input focused while preserving the fields that identify a row."""
    preferred = [
        "source_file",
        "id",
        "domain",
        "question",
        "questions",
        "problem",
        "prompt",
        "answer",
        "answers",
        "graphs",
        "images",
    ]
    record = {"row_index": index}
    for key in preferred:
        if key in row:
            if key in {"graphs", "images"}:
                value = row[key]
                record[key] = {
                    "count": len(value) if isinstance(value, list) else None,
                    "omitted": "Raw visual payload excluded from judge input.",
                }
            else:
                record[key] = row[key]
    if len(record) == 1:
        record.update(row)
    return record


def json_default(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def build_messages(prompt: str, record: dict[str, Any]) -> list[dict[str, str]]:
    record_json = json.dumps(record, ensure_ascii=False, indent=2, default=json_default)
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"Dataset record:\n```json\n{record_json}\n```"},
    ]


def build_user_prompt(record: dict[str, Any]) -> str:
    record_json = json.dumps(record, ensure_ascii=False, indent=2, default=json_default)
    return f"Dataset record:\n```json\n{record_json}\n```"


def parse_judge_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        data = json.loads(text[start : end + 1])

    if not isinstance(data, dict):
        raise ValueError("Judge response must be a JSON object.")

    verdict = data.get("verdict")
    if verdict is None and isinstance(data.get("label"), str):
        verdict = LEGACY_LABEL_TO_VERDICT.get(data["label"])
    if verdict is None and isinstance(data.get("keep"), bool):
        verdict = "fully_final_answerable" if data["keep"] else "non_final_answerable"
    if verdict not in FINAL_ANSWERABLE_VERDICTS:
        expected = ", ".join(sorted(FINAL_ANSWERABLE_VERDICTS))
        raise ValueError(f"Judge response must contain verdict in: {expected}.")

    data["verdict"] = verdict
    data["keep"] = verdict in KEEP_VERDICTS
    data.setdefault("label", verdict)
    data.setdefault("reason", "")
    return data


def judge_record(
    client: OpenAI,
    *,
    model: str,
    prompt: str,
    record: dict[str, Any],
    temperature: float,
    max_tokens: int,
    json_mode: bool,
) -> tuple[dict[str, Any], str]:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": build_messages(prompt, record),
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    raw = response.choices[0].message.content or ""
    return parse_judge_json(raw), raw


def judge_record_codex(
    client: CodexLLM,
    *,
    prompt: str,
    record: dict[str, Any],
    api_key: str | None,
) -> tuple[dict[str, Any], str]:
    result = client.complete(
        f"{prompt}\n\n{build_user_prompt(record)}",
        api_key=api_key,
    )
    return parse_judge_json(result.text), result.text


def fallback_decision(error: Exception, on_error: str) -> dict[str, Any]:
    if on_error == "fail":
        raise error
    keep = on_error == "keep"
    return {
        "keep": keep,
        "verdict": "fully_final_answerable" if keep else "non_final_answerable",
        "label": "error_keep" if keep else "error_drop",
        "reason": f"Judge failed: {error}",
    }


@dataclass
class JudgeConfig:
    backend: str
    client: Any
    model: str | None
    prompt: str
    temperature: float
    max_tokens: int
    json_mode: bool
    api_key: str | None
    on_error: str
    output_mode: str


@dataclass
class RowDecision:
    index: int
    keep: bool
    decision: dict[str, Any]


def write_decision(handle: Any, decision: dict[str, Any]) -> None:
    handle.write(json.dumps(decision, ensure_ascii=False, default=json_default) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def load_existing_decisions(decisions_path: Path, rows: list[dict[str, Any]]) -> list[RowDecision | None]:
    decisions: list[RowDecision | None] = [None] * len(rows)
    if not decisions_path.exists():
        return decisions

    with decisions_path.open("r", encoding="utf-8") as decisions_file:
        for line_number, line in enumerate(decisions_file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                decision = json.loads(line)
            except json.JSONDecodeError:
                print(
                    f"Skipping malformed checkpoint line {line_number} in {decisions_path}",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            index = decision.get("row_index")
            if not isinstance(index, int) or index < 0 or index >= len(rows):
                continue

            row_id = rows[index].get("id")
            if decision.get("id") != row_id:
                print(
                    f"Skipping checkpoint row {index}: id mismatch "
                    f"({decision.get('id')!r} != {row_id!r})",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            row_source = rows[index].get("source_file")
            if row_source is not None and decision.get("source_file") != row_source:
                print(
                    f"Skipping checkpoint row {index}: source_file mismatch "
                    f"({decision.get('source_file')!r} != {row_source!r})",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            verdict = decision.get("verdict")
            if verdict not in FINAL_ANSWERABLE_VERDICTS:
                print(
                    f"Skipping checkpoint row {index}: invalid verdict {verdict!r}",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            decision = dict(decision)
            decision.pop("split", None)
            decision["keep"] = verdict in KEEP_VERDICTS
            decision.setdefault("label", verdict)
            decision.setdefault("reason", "")
            decisions[index] = RowDecision(
                index=index,
                keep=bool(decision["keep"]),
                decision=decision,
            )

    return decisions


def ensure_checkpoint_append_boundary(decisions_path: Path) -> None:
    if not decisions_path.exists() or decisions_path.stat().st_size == 0:
        return
    with decisions_path.open("rb+") as decisions_file:
        decisions_file.seek(-1, os.SEEK_END)
        if decisions_file.read(1) != b"\n":
            decisions_file.write(b"\n")
            decisions_file.flush()
            os.fsync(decisions_file.fileno())


def count_present_decisions(decisions: list[RowDecision | None]) -> int:
    return sum(result is not None for result in decisions)


def write_checkpoint_snapshot(
    decisions_path: Path,
    *,
    split_name: str,
    decisions: list[RowDecision | None],
) -> None:
    with decisions_path.open("w", encoding="utf-8") as decisions_file:
        for result in decisions:
            if result is not None:
                append_checkpoint(decisions_file, split_name=split_name, result=result)


def append_checkpoint(
    handle: Any,
    *,
    split_name: str,
    result: RowDecision,
) -> None:
    write_decision(handle, {"split": split_name, **result.decision})


def judge_row(index: int, row: dict[str, Any], config: JudgeConfig) -> RowDecision:
    record = compact_record(row, index)
    started = time.time()
    raw_response = ""
    try:
        if config.backend == "openai":
            judge, raw_response = judge_record(
                config.client,
                model=config.model or "gpt-4o-mini",
                prompt=config.prompt,
                record=record,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                json_mode=config.json_mode,
            )
        elif config.backend == "codex-cli":
            judge, raw_response = judge_record_codex(
                config.client,
                prompt=config.prompt,
                record=record,
                api_key=config.api_key,
            )
        else:
            raise ValueError(f"Unknown judge backend: {config.backend}")
    except Exception as exc:
        judge = fallback_decision(exc, config.on_error)

    keep = bool(judge["keep"])
    decision = {
        "row_index": index,
        "id": row.get("id"),
        "source_file": row.get("source_file"),
        "keep": keep,
        "verdict": judge.get("verdict"),
        "label": judge.get("label"),
        "gold_label": row.get("label"),
        "reason": judge.get("reason"),
        "latency_seconds": round(time.time() - started, 3),
        "raw_response": raw_response,
    }
    return RowDecision(index=index, keep=keep, decision=decision)


def filter_split(
    split_path: Path,
    *,
    input_dir: Path,
    output_dir: Path,
    decisions_dir: Path,
    config: JudgeConfig,
    limit: int | None,
    workers: int,
) -> dict[str, int]:
    split_name = split_path.name
    rel_path = split_path.relative_to(input_dir)
    out_path = output_dir / rel_path
    decisions_path = decisions_dir / rel_path.with_suffix(".jsonl")

    table = pq.read_table(split_path)
    rows = table.to_pylist()
    if limit is not None:
        rows = rows[:limit]

    print(f"Filtering {split_name}: {len(rows)} row(s)", flush=True)
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    decisions = load_existing_decisions(decisions_path, rows)
    existing_count = count_present_decisions(decisions)

    legacy_decisions_path = decisions_dir / f"{split_path.stem}.jsonl"
    if existing_count == 0 and legacy_decisions_path != decisions_path:
        legacy_decisions = load_existing_decisions(legacy_decisions_path, rows)
        legacy_count = count_present_decisions(legacy_decisions)
        if legacy_count:
            decisions = legacy_decisions
            existing_count = legacy_count
            write_checkpoint_snapshot(
                decisions_path,
                split_name=split_name,
                decisions=decisions,
            )
            print(
                f"  Migrated {legacy_count}/{len(rows)} legacy decision(s) "
                f"from {legacy_decisions_path} to {decisions_path}",
                flush=True,
            )

    pending = [(index, row) for index, row in enumerate(rows) if decisions[index] is None]

    if existing_count:
        print(
            f"  Resuming from {decisions_path}: "
            f"{existing_count}/{len(rows)} row decision(s) already present",
            flush=True,
        )
    if not pending:
        print("  No pending rows; rebuilding parquet output from checkpoint.", flush=True)

    ensure_checkpoint_append_boundary(decisions_path)
    with decisions_path.open("a", encoding="utf-8") as decisions_file:
        if workers <= 1:
            for completed, (index, row) in enumerate(pending, start=1):
                result = judge_row(index, row, config)
                decisions[index] = result
                append_checkpoint(decisions_file, split_name=split_name, result=result)
                print_progress(result, len(pending), completed=completed)
        elif pending:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_index = {
                    executor.submit(judge_row, index, row, config): index for index, row in pending
                }
                completed = 0
                for future in as_completed(future_to_index):
                    result = future.result()
                    decisions[result.index] = result
                    append_checkpoint(decisions_file, split_name=split_name, result=result)
                    completed += 1
                    print_progress(result, len(pending), completed=completed)

    keep_mask: list[bool] = []
    verdicts: list[str] = []
    for result in decisions:
        if result is None:
            raise RuntimeError("Internal error: missing row decision.")
        keep_mask.append(result.keep)
        verdict = result.decision.get("verdict")
        if verdict not in FINAL_ANSWERABLE_VERDICTS:
            raise RuntimeError(f"Internal error: invalid verdict {verdict!r}.")
        verdicts.append(verdict)

    input_slice = table.slice(0, len(rows))
    counts = {verdict: verdicts.count(verdict) for verdict in sorted(FINAL_ANSWERABLE_VERDICTS)}

    if config.output_mode in {"kept", "both"}:
        filtered = input_slice.filter(pa.array(keep_mask, type=pa.bool_()))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(filtered, out_path)
        print(f"Wrote {filtered.num_rows}/{len(rows)} row(s) to {out_path}", flush=True)

    if config.output_mode in {"verdict-subsets", "both"}:
        subset_dir = output_dir / rel_path.with_suffix("")
        subset_dir.mkdir(parents=True, exist_ok=True)
        for verdict in sorted(FINAL_ANSWERABLE_VERDICTS):
            mask = [item == verdict for item in verdicts]
            subset = input_slice.filter(pa.array(mask, type=pa.bool_()))
            subset_path = subset_dir / f"{verdict}.parquet"
            pq.write_table(subset, subset_path)
            print(f"Wrote {subset.num_rows}/{len(rows)} row(s) to {subset_path}", flush=True)

    return counts


def print_progress(result: RowDecision | None, total: int, completed: int | None = None) -> None:
    if result is None:
        return
    decision = result.decision
    status = "keep" if result.keep else "drop"
    verdict = decision.get("verdict", decision.get("label", "unknown"))
    position = completed if completed is not None else result.index + 1
    print(
        f"  [{position}/{total}] row {result.index + 1}: "
        f"{status} {verdict}: {decision.get('reason', '')}",
        flush=True,
    )


def build_judge_config(args: argparse.Namespace, prompt: str) -> JudgeConfig:
    if args.judge_backend == "openai":
        if not args.api_key:
            print("OPENAI_API_KEY is required for --judge-backend openai.", file=sys.stderr)
            raise SystemExit(2)
        client_kwargs: dict[str, Any] = {
            "api_key": args.api_key,
            "timeout": args.timeout,
            "max_retries": args.max_retries,
        }
        if args.base_url:
            client_kwargs["base_url"] = args.base_url
        client = OpenAI(**client_kwargs)
        model = args.model or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
    else:
        client = CodexLLM(
            model=args.model or os.getenv("CODEX_LLM_MODEL"),
            model_reasoning_effort=args.model_reasoning_effort,
            codex_bin=args.codex_bin,
            timeout=args.timeout,
            max_tool_retries=args.max_tool_retries,
            max_exec_retries=args.max_exec_retries,
            exec_retry_delay=args.exec_retry_delay,
        )
        model = args.model or os.getenv("CODEX_LLM_MODEL")

    return JudgeConfig(
        backend=args.judge_backend,
        client=client,
        model=model,
        prompt=prompt,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        json_mode=not args.no_json_mode,
        api_key=args.api_key,
        on_error=args.on_error,
        output_mode=args.output_mode,
    )


def main() -> int:
    args = parse_args()
    if args.workers < 1:
        print("--workers must be at least 1.", file=sys.stderr)
        return 2

    prompt = load_prompt(args.prompt_file)
    split_files = list_split_files(args.input_dir, args.splits)
    config = build_judge_config(args, prompt)
    decisions_dir = args.decisions_dir

    for split_path in split_files:
        filter_split(
            split_path,
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            decisions_dir=decisions_dir,
            config=config,
            limit=args.limit,
            workers=args.workers,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
