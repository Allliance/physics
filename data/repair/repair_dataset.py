#!/usr/bin/env python3
"""Repair partially final-answerable physics problems with an LLM."""

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


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.codex_cli import CodexLLM


DEFAULT_INPUT_DIR = REPO_ROOT / "data" / "repair" / "dev_set"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "repair" / "outputs" / "dev_set"
DEFAULT_REPAIRS_DIR = REPO_ROOT / "data" / "repair" / "repairs" / "dev_set"
DEFAULT_PROMPT = Path(__file__).resolve().parent / "repair_prompt.txt"
NO_FINAL_ANSWERABLE_CONTENT = "[NO_FINAL_ANSWERABLE_CONTENT]"
SUPPORTED_SUFFIXES = {".json", ".parquet"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair partially final-answerable physics problem splits."
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--repairs-dir", type=Path, default=DEFAULT_REPAIRS_DIR)
    parser.add_argument("--prompt-file", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument(
        "--repair-backend",
        choices=("openai", "codex-cli"),
        default="openai",
        help="Backend used for repairing each record.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of records to repair in parallel.",
    )
    parser.add_argument(
        "--splits",
        nargs="*",
        help="Split filenames to process. Defaults to every supported file in input-dir.",
    )
    parser.add_argument("--model")
    parser.add_argument("--model-reasoning-effort", default=os.getenv("CODEX_LLM_REASONING_EFFORT"))
    parser.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL"))
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY"))
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--codex-bin", default=os.getenv("CODEX_BIN", "codex"))
    parser.add_argument("--max-tool-retries", type=int, default=3)
    parser.add_argument("--max-exec-retries", type=int, default=6)
    parser.add_argument("--exec-retry-delay", type=float, default=10.0)
    parser.add_argument("--limit", type=int, help="Only process the first N rows per split.")
    parser.add_argument(
        "--on-error",
        choices=("fail", "keep-original", "mark-no-content"),
        default="fail",
        help="What to write if a repair call fails.",
    )
    parser.add_argument(
        "--output-mode",
        choices=("add-columns", "replace-question"),
        default="replace-question",
        help=(
            "add-columns preserves the original question and adds repaired_question; "
            "replace-question writes the repaired text into question and keeps original_question."
        ),
    )
    parser.add_argument(
        "--output-filename",
        help=(
            "Write every repaired split using this filename in the corresponding "
            "relative output directory."
        ),
    )
    parser.add_argument(
        "--drop-no-content",
        action="store_true",
        help="Drop rows whose repair is exactly [NO_FINAL_ANSWERABLE_CONTENT].",
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
        files = sorted(path for path in input_dir.iterdir() if path.suffix in SUPPORTED_SUFFIXES)
    missing = [str(path) for path in files if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing split file(s): " + ", ".join(missing))
    unsupported = [str(path) for path in files if path.suffix not in SUPPORTED_SUFFIXES]
    if unsupported:
        raise ValueError("Unsupported split file(s): " + ", ".join(unsupported))
    if not files:
        expected = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise FileNotFoundError(f"No supported split files ({expected}) found in {input_dir}")
    return files


def load_rows(path: Path) -> tuple[list[dict[str, Any]], Any | None]:
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"JSON split must contain a list of records: {path}")
        rows = []
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                raise ValueError(f"JSON record {index} is not an object in {path}")
            rows.append(item)
        return rows, None

    if path.suffix == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise RuntimeError("pyarrow is required to read parquet splits.") from exc
        table = pq.read_table(path)
        return table.to_pylist(), table.schema

    raise ValueError(f"Unsupported split suffix: {path.suffix}")


def json_default(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def question_field_name(row: dict[str, Any]) -> str:
    for field in ("question", "questions"):
        value = row.get(field)
        if isinstance(value, str) and value.strip():
            return field
    raise ValueError("Record must contain a non-empty string field named 'question' or 'questions'.")


def build_user_prompt(row: dict[str, Any]) -> str:
    question = row.get(question_field_name(row))
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Record must contain a non-empty string field named 'question' or 'questions'.")
    return f"Original problem statement:\n\n{question}"


def normalize_repair_text(text: str) -> str:
    repaired = text.strip()
    if repaired.startswith("```") and repaired.endswith("```"):
        lines = repaired.splitlines()
        if len(lines) >= 3:
            repaired = "\n".join(lines[1:-1]).strip()
    if not repaired:
        raise ValueError("Repair response was empty.")
    return repaired


def repair_status(repaired_question: str) -> str:
    if repaired_question.strip() == NO_FINAL_ANSWERABLE_CONTENT:
        return "no_final_answerable_content"
    return "repaired"


@dataclass
class RepairConfig:
    backend: str
    client: Any
    model: str | None
    prompt: str
    temperature: float
    max_tokens: int
    api_key: str | None
    on_error: str
    output_mode: str
    drop_no_content: bool


@dataclass
class RowRepair:
    index: int
    repaired_question: str
    status: str
    repair: dict[str, Any]


def repair_record_openai(
    client: Any,
    *,
    model: str,
    prompt: str,
    row: dict[str, Any],
    temperature: float,
    max_tokens: int,
) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": build_user_prompt(row)},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


def repair_record_codex(
    client: CodexLLM,
    *,
    prompt: str,
    row: dict[str, Any],
    api_key: str | None,
) -> str:
    result = client.complete(
        build_user_prompt(row),
        system_prompt=prompt,
        api_key=api_key,
    )
    return result.text


def fallback_repair(error: Exception, row: dict[str, Any], on_error: str) -> str:
    if on_error == "fail":
        raise error
    if on_error == "keep-original":
        question = row.get("question")
        if not isinstance(question, str):
            raise error
        return question
    return NO_FINAL_ANSWERABLE_CONTENT


def repair_row(index: int, row: dict[str, Any], config: RepairConfig) -> RowRepair:
    started = time.time()
    raw_response = ""
    error_message = ""
    try:
        if config.backend == "openai":
            raw_response = repair_record_openai(
                config.client,
                model=config.model or "gpt-4o-mini",
                prompt=config.prompt,
                row=row,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )
        elif config.backend == "codex-cli":
            raw_response = repair_record_codex(
                config.client,
                prompt=config.prompt,
                row=row,
                api_key=config.api_key,
            )
        else:
            raise ValueError(f"Unknown repair backend: {config.backend}")
        repaired_question = normalize_repair_text(raw_response)
    except Exception as exc:
        error_message = str(exc)
        repaired_question = fallback_repair(exc, row, config.on_error)

    status = repair_status(repaired_question)
    if error_message:
        status = "error_" + status

    repair = {
        "row_index": index,
        "id": row.get("id"),
        "source_file": row.get("source_file"),
        "status": status,
        "latency_seconds": round(time.time() - started, 3),
        "repaired_question": repaired_question,
        "raw_response": raw_response,
    }
    if error_message:
        repair["error"] = error_message
    return RowRepair(
        index=index,
        repaired_question=repaired_question,
        status=status,
        repair=repair,
    )


def write_repair(handle: Any, repair: dict[str, Any]) -> None:
    handle.write(json.dumps(repair, ensure_ascii=False, default=json_default) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def load_existing_repairs(repairs_path: Path, rows: list[dict[str, Any]]) -> list[RowRepair | None]:
    repairs: list[RowRepair | None] = [None] * len(rows)
    if not repairs_path.exists():
        return repairs

    with repairs_path.open("r", encoding="utf-8") as repairs_file:
        for line_number, line in enumerate(repairs_file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                repair = json.loads(line)
            except json.JSONDecodeError:
                print(
                    f"Skipping malformed checkpoint line {line_number} in {repairs_path}",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            index = repair.get("row_index")
            if not isinstance(index, int) or index < 0 or index >= len(rows):
                continue

            row_id = rows[index].get("id")
            if repair.get("id") != row_id:
                print(
                    f"Skipping checkpoint row {index}: id mismatch "
                    f"({repair.get('id')!r} != {row_id!r})",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            row_source = rows[index].get("source_file")
            if row_source is not None and repair.get("source_file") != row_source:
                print(
                    f"Skipping checkpoint row {index}: source_file mismatch "
                    f"({repair.get('source_file')!r} != {row_source!r})",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            repaired_question = repair.get("repaired_question")
            status = repair.get("status")
            if not isinstance(repaired_question, str) or not isinstance(status, str):
                print(
                    f"Skipping checkpoint row {index}: missing repaired_question/status",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            repair = dict(repair)
            repair.pop("split", None)
            repairs[index] = RowRepair(
                index=index,
                repaired_question=repaired_question,
                status=status,
                repair=repair,
            )

    return repairs


def ensure_checkpoint_append_boundary(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        return
    with path.open("rb+") as repairs_file:
        repairs_file.seek(-1, os.SEEK_END)
        if repairs_file.read(1) != b"\n":
            repairs_file.write(b"\n")
            repairs_file.flush()
            os.fsync(repairs_file.fileno())


def append_checkpoint(handle: Any, *, split_name: str, result: RowRepair) -> None:
    write_repair(handle, {"split": split_name, **result.repair})


def count_present_repairs(repairs: list[RowRepair | None]) -> int:
    return sum(result is not None for result in repairs)


def print_progress(result: RowRepair, total: int, completed: int) -> None:
    preview = result.repaired_question.replace("\n", " ")[:90]
    print(
        f"  [{completed}/{total}] row {result.index + 1}: {result.status}: {preview}",
        flush=True,
    )


def build_output_rows(
    rows: list[dict[str, Any]],
    repairs: list[RowRepair],
    *,
    output_mode: str,
    drop_no_content: bool,
) -> list[dict[str, Any]]:
    output_rows = []
    for row, repair in zip(rows, repairs, strict=True):
        if drop_no_content and repair.repaired_question.strip() == NO_FINAL_ANSWERABLE_CONTENT:
            continue

        output_row = dict(row)
        if output_mode == "replace-question":
            question_field = question_field_name(row)
            original_question_field = f"original_{question_field}"
            output_row = {}
            placed_question = False
            for key, value in row.items():
                if key == question_field:
                    output_row[question_field] = repair.repaired_question
                    output_row[original_question_field] = value
                    placed_question = True
                else:
                    output_row[key] = value
            if not placed_question:
                output_row[question_field] = repair.repaired_question
                output_row[original_question_field] = row.get(question_field)
        else:
            output_row["repaired_question"] = repair.repaired_question
        output_row["repair_status"] = repair.status
        output_rows.append(output_row)
    return output_rows


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=json_default) + "\n")
        return

    if path.suffix == ".parquet":
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise RuntimeError("pyarrow is required to write parquet splits.") from exc
        pq.write_table(pa.Table.from_pylist(rows), path)
        return

    raise ValueError(f"Unsupported output suffix: {path.suffix}")


def repair_split(
    split_path: Path,
    *,
    input_dir: Path,
    output_dir: Path,
    repairs_dir: Path,
    config: RepairConfig,
    limit: int | None,
    workers: int,
    output_filename: str | None,
) -> dict[str, int]:
    split_name = split_path.name
    rel_path = split_path.relative_to(input_dir)
    out_rel_path = rel_path.with_name(output_filename) if output_filename else rel_path
    if out_rel_path.suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported output filename suffix: {out_rel_path.suffix}")
    out_path = output_dir / out_rel_path
    repairs_path = repairs_dir / rel_path.with_suffix(".jsonl")

    rows, _schema = load_rows(split_path)
    if limit is not None:
        rows = rows[:limit]

    print(f"Repairing {split_name}: {len(rows)} row(s)", flush=True)
    repairs_path.parent.mkdir(parents=True, exist_ok=True)
    repairs = load_existing_repairs(repairs_path, rows)
    existing_count = count_present_repairs(repairs)
    pending = [(index, row) for index, row in enumerate(rows) if repairs[index] is None]

    if existing_count:
        print(
            f"  Resuming from {repairs_path}: "
            f"{existing_count}/{len(rows)} row repair(s) already present",
            flush=True,
        )
    if not pending:
        print("  No pending rows; rebuilding output from checkpoint.", flush=True)

    ensure_checkpoint_append_boundary(repairs_path)
    with repairs_path.open("a", encoding="utf-8") as repairs_file:
        if workers <= 1:
            for completed, (index, row) in enumerate(pending, start=1):
                result = repair_row(index, row, config)
                repairs[index] = result
                append_checkpoint(repairs_file, split_name=split_name, result=result)
                print_progress(result, len(pending), completed)
        elif pending:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_index = {
                    executor.submit(repair_row, index, row, config): index for index, row in pending
                }
                completed = 0
                for future in as_completed(future_to_index):
                    result = future.result()
                    repairs[result.index] = result
                    append_checkpoint(repairs_file, split_name=split_name, result=result)
                    completed += 1
                    print_progress(result, len(pending), completed)

    completed_repairs: list[RowRepair] = []
    for result in repairs:
        if result is None:
            raise RuntimeError("Internal error: missing row repair.")
        completed_repairs.append(result)

    output_rows = build_output_rows(
        rows,
        completed_repairs,
        output_mode=config.output_mode,
        drop_no_content=config.drop_no_content,
    )
    write_rows(out_path, output_rows)
    print(f"Wrote {len(output_rows)}/{len(rows)} row(s) to {out_path}", flush=True)

    return {
        "input_rows": len(rows),
        "output_rows": len(output_rows),
        "no_final_answerable_content": sum(
            result.repaired_question.strip() == NO_FINAL_ANSWERABLE_CONTENT
            for result in completed_repairs
        ),
    }


def build_repair_config(args: argparse.Namespace, prompt: str) -> RepairConfig:
    if args.repair_backend == "openai":
        if not args.api_key:
            print("OPENAI_API_KEY is required for --repair-backend openai.", file=sys.stderr)
            raise SystemExit(2)
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai is required for --repair-backend openai.") from exc

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

    return RepairConfig(
        backend=args.repair_backend,
        client=client,
        model=model,
        prompt=prompt,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        api_key=args.api_key,
        on_error=args.on_error,
        output_mode=args.output_mode,
        drop_no_content=args.drop_no_content,
    )


def main() -> int:
    args = parse_args()
    if args.workers < 1:
        print("--workers must be at least 1.", file=sys.stderr)
        return 2

    prompt = load_prompt(args.prompt_file)
    split_files = list_split_files(args.input_dir, args.splits)
    config = build_repair_config(args, prompt)

    totals = {"input_rows": 0, "output_rows": 0, "no_final_answerable_content": 0}
    for split_path in split_files:
        counts = repair_split(
            split_path,
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            repairs_dir=args.repairs_dir,
            config=config,
            limit=args.limit,
            workers=args.workers,
            output_filename=args.output_filename,
        )
        for key, value in counts.items():
            totals[key] += value

    print(
        "Done: "
        f"{totals['output_rows']}/{totals['input_rows']} output row(s), "
        f"{totals['no_final_answerable_content']} no-content repair(s).",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
