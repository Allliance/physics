#!/usr/bin/env python3
"""Filter prepared parquet datasets with an OpenAI-compatible LLM judge."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from openai import OpenAI


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = REPO_ROOT / "original_datasets" / "prepared" / "FrontierPhysics"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "filtered_datasets" / "prepared" / "FrontierPhysics"
DEFAULT_DECISIONS_DIR = REPO_ROOT / "data" / "filter" / "decisions" / "FrontierPhysics"
DEFAULT_PROMPT = Path(__file__).resolve().parent / "prompts" / "final_answerable.txt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Filter parquet dataset splits using an OpenAI-compatible LLM judge."
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--decisions-dir", type=Path, default=DEFAULT_DECISIONS_DIR)
    parser.add_argument("--prompt-file", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument(
        "--splits",
        nargs="*",
        help="Parquet split filenames to process. Defaults to every *.parquet in input-dir.",
    )
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    parser.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL"))
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY"))
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=300)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-retries", type=int, default=2)
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
        "final_answers",
        "answer",
        "answers",
        "rubric",
    ]
    record = {"row_index": index}
    for key in preferred:
        if key in row:
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
    if "keep" not in data or not isinstance(data["keep"], bool):
        raise ValueError("Judge response must contain boolean field 'keep'.")
    data.setdefault("label", "final_answerable" if data["keep"] else "descriptive")
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


def fallback_decision(error: Exception, on_error: str) -> dict[str, Any]:
    if on_error == "fail":
        raise error
    keep = on_error == "keep"
    return {
        "keep": keep,
        "label": "error_keep" if keep else "error_drop",
        "reason": f"Judge failed: {error}",
    }


def write_decision(handle: Any, decision: dict[str, Any]) -> None:
    handle.write(json.dumps(decision, ensure_ascii=False, default=json_default) + "\n")
    handle.flush()


def filter_split(
    split_path: Path,
    *,
    input_dir: Path,
    output_dir: Path,
    decisions_dir: Path,
    client: OpenAI,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    limit: int | None,
    on_error: str,
    json_mode: bool,
) -> None:
    split_name = split_path.name
    rel_path = split_path.relative_to(input_dir)
    out_path = output_dir / rel_path
    decisions_path = decisions_dir / f"{split_path.stem}.jsonl"

    table = pq.read_table(split_path)
    rows = table.to_pylist()
    if limit is not None:
        rows = rows[:limit]

    print(f"Filtering {split_name}: {len(rows)} row(s)", flush=True)
    keep_mask: list[bool] = []
    decisions_path.parent.mkdir(parents=True, exist_ok=True)

    with decisions_path.open("w", encoding="utf-8") as decisions_file:
        for index, row in enumerate(rows):
            record = compact_record(row, index)
            started = time.time()
            raw_response = ""
            try:
                judge, raw_response = judge_record(
                    client,
                    model=model,
                    prompt=prompt,
                    record=record,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
            except Exception as exc:
                judge = fallback_decision(exc, on_error)

            keep = bool(judge["keep"])
            keep_mask.append(keep)
            write_decision(
                decisions_file,
                {
                    "split": split_name,
                    "row_index": index,
                    "id": row.get("id"),
                    "source_file": row.get("source_file"),
                    "keep": keep,
                    "label": judge.get("label"),
                    "reason": judge.get("reason"),
                    "latency_seconds": round(time.time() - started, 3),
                    "raw_response": raw_response,
                },
            )

            status = "keep" if keep else "drop"
            print(f"  [{index + 1}/{len(rows)}] {status}: {judge.get('reason', '')}", flush=True)

    filtered = table.slice(0, len(rows)).filter(pa.array(keep_mask, type=pa.bool_()))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(filtered, out_path)
    print(f"Wrote {filtered.num_rows}/{len(rows)} row(s) to {out_path}", flush=True)


def main() -> int:
    args = parse_args()
    if not args.api_key:
        print("OPENAI_API_KEY is required, or pass --api-key.", file=sys.stderr)
        return 2

    prompt = load_prompt(args.prompt_file)
    split_files = list_split_files(args.input_dir, args.splits)
    client_kwargs: dict[str, Any] = {
        "api_key": args.api_key,
        "timeout": args.timeout,
        "max_retries": args.max_retries,
    }
    if args.base_url:
        client_kwargs["base_url"] = args.base_url
    client = OpenAI(**client_kwargs)
    decisions_dir = args.decisions_dir

    for split_path in split_files:
        filter_split(
            split_path,
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            decisions_dir=decisions_dir,
            client=client,
            model=args.model,
            prompt=prompt,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            limit=args.limit,
            on_error=args.on_error,
            json_mode=not args.no_json_mode,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
