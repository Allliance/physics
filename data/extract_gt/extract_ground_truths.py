#!/usr/bin/env python3
"""Extract exact, part-aligned ground truths from worked physics solutions."""

from __future__ import annotations

import argparse
import json
import os
import re
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


HERE = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = HERE / "dev_set"
DEFAULT_OUTPUT_DIR = HERE / "outputs" / "dev_set"
DEFAULT_PROMPT = HERE / "extract_prompt.txt"
SUPPORTED_SUFFIXES = {".json", ".jsonl", ".parquet"}
PART_MARKER = re.compile(r"(?<![A-Za-z0-9])\(([a-z])\)\s+", re.IGNORECASE)
CONTENT_TOKEN = re.compile(r"\\[A-Za-z]+|[A-Za-z]+|\d+(?:\.\d+)?|[=+*/^_<>-]")


class ExtractionValidationError(ValueError):
    """The model response is not a verifiable extraction."""


class RowExtractionError(RuntimeError):
    """A row still failed after all configured extraction attempts."""

    def __init__(self, index: int, row: dict[str, Any], attempts: int, errors: list[str]):
        self.index = index
        self.row = row
        self.attempts = attempts
        self.errors = errors
        super().__init__(
            f"row {index} ({row.get('id', '<no id>')}) failed after {attempts} attempts: "
            + " | ".join(errors)
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, nargs="*", help="Input JSON, JSONL, or parquet files.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--prompt-file", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--model-reasoning-effort", default="high")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--max-extraction-attempts",
        type=int,
        default=3,
        help="Total LLM attempts per row before recording it as a failure.",
    )
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--api-key", default=os.getenv("CODEX_API_KEY"))
    parser.add_argument("--codex-bin", default=os.getenv("CODEX_BIN", "codex"))
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def list_inputs(explicit: list[Path], input_dir: Path) -> list[Path]:
    paths = explicit or sorted(p for p in input_dir.iterdir() if p.suffix in SUPPORTED_SUFFIXES)
    if not paths:
        raise FileNotFoundError(f"No supported inputs found in {input_dir}")
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.suffix not in SUPPORTED_SUFFIXES:
            raise ValueError(f"Unsupported input type: {path}")
    return paths


def load_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
            raise ValueError(f"Expected a JSON list of objects: {path}")
        return data
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("pyarrow is required for parquet input") from exc
    return pq.read_table(path).to_pylist()


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return
    if path.suffix == ".jsonl":
        text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        path.write_text(text, encoding="utf-8")
        return
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("pyarrow is required for parquet output") from exc
    # Store the dictionary as JSON so parquet schemas stay stable across rows with
    # different numbers of parts.
    parquet_rows = []
    for row in rows:
        item = dict(row)
        if isinstance(item.get("ground_truths"), dict):
            item["ground_truths"] = json.dumps(
                item["ground_truths"], ensure_ascii=False
            )
        if isinstance(item.get("null_answer_reasons"), dict):
            item["null_answer_reasons"] = json.dumps(
                item["null_answer_reasons"], ensure_ascii=False
            )
        parquet_rows.append(item)
    pq.write_table(pa.Table.from_pylist(parquet_rows), path)


def infer_part_labels(question: str, is_multi_part: bool) -> list[str]:
    """Infer the consecutive question labels, ignoring incidental later variables."""
    if not is_multi_part:
        return ["a"]
    matches = [(m.group(1).lower(), m.start()) for m in PART_MARKER.finditer(question)]
    labels: list[str] = []
    cursor = -1
    for code in range(ord("a"), ord("z") + 1):
        label = chr(code)
        positions = [pos for found, pos in matches if found == label and pos > cursor]
        if not positions:
            break
        cursor = positions[0]
        labels.append(label)
    if len(labels) < 2:
        raise ValueError("Multi-part question does not contain a consecutive (a), (b), ... sequence")
    return labels


def sub_questions(question: str, labels: list[str]) -> dict[str, str]:
    """Return the exact question text associated with each inferred part."""
    if labels == ["a"] and not PART_MARKER.search(question):
        return {"a": question}
    matches = [match for match in PART_MARKER.finditer(question) if match.group(1).lower() in labels]
    selected = []
    cursor = -1
    for label in labels:
        match = next(
            (candidate for candidate in matches if candidate.group(1).lower() == label and candidate.start() > cursor),
            None,
        )
        if match is None:
            return {part: question for part in labels}
        selected.append(match)
        cursor = match.start()
    result = {}
    for index, (label, match) in enumerate(zip(labels, selected)):
        end = selected[index + 1].start() if index + 1 < len(selected) else len(question)
        result[label] = question[match.end() : end].strip()
    return result


def build_user_prompt(row: dict[str, Any], labels: list[str], retry_note: str = "") -> str:
    question = row.get("question")
    solution = row.get("solution")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Row has no non-empty question")
    if not isinstance(solution, str) or not solution.strip():
        raise ValueError("Row has no non-empty solution")
    note = f"\n\nRETRY FEEDBACK:\n{retry_note}" if retry_note else ""
    return (
        f"Required dictionary keys: {json.dumps(labels)}\n\n"
        f"QUESTION:\n{question}\n\nSOLUTION:\n{solution}{note}"
    )


def content_tokens(text: str) -> list[str]:
    """Tokenize semantic content while ignoring delimiters and punctuation."""
    return CONTENT_TOKEN.findall(text)


def is_ordered_token_subsequence(answer: str, solution: str) -> bool:
    """Check that answer's meaningful tokens were selected from solution in order."""
    answer_tokens = content_tokens(answer)
    solution_tokens = iter(content_tokens(solution))
    return all(any(candidate == token for candidate in solution_tokens) for token in answer_tokens)


def parse_and_verify(
    text: str, solution: str, labels: list[str]
) -> tuple[dict[str, str | None], dict[str, str]]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExtractionValidationError(f"response is not JSON: {exc}") from exc
    if not isinstance(value, dict) or set(value) != {"ground_truths", "null_answer_reasons"}:
        raise ExtractionValidationError(
            "response must contain exactly 'ground_truths' and 'null_answer_reasons' dictionaries"
        )
    answers = value["ground_truths"]
    reasons = value["null_answer_reasons"]
    if not isinstance(answers, dict) or not isinstance(reasons, dict):
        raise ExtractionValidationError("ground_truths and null_answer_reasons must be dictionaries")
    if list(answers) != labels:
        raise ExtractionValidationError(
            f"ground_truth keys must be exactly {labels} in that order; received {list(answers)}"
        )
    failures = []
    null_labels = [label for label, answer in answers.items() if answer is None]
    if list(reasons) != null_labels:
        failures.append(
            f"null_answer_reasons keys must be exactly the null-answer keys {null_labels} in order"
        )
    for label, answer in answers.items():
        if answer is None:
            reason = reasons.get(label)
            if not isinstance(reason, str) or not reason.strip():
                failures.append(f"{label}: null answer requires a non-empty reason")
        elif not isinstance(answer, str) or not answer.strip():
            failures.append(f"{label}: answer must be a non-empty string or null")
        elif not is_ordered_token_subsequence(answer, solution):
            failures.append(
                f"{label}: answer contains meaningful content absent from, repeated beyond, or reordered relative to SOLUTION"
            )
    if failures:
        raise ExtractionValidationError("; ".join(failures))
    return answers, reasons


@dataclass(frozen=True)
class Config:
    prompt: str
    api_key: str | None
    max_attempts: int


def extract_one(index: int, row: dict[str, Any], client: CodexLLM, config: Config) -> tuple[int, dict[str, Any]]:
    labels = infer_part_labels(str(row.get("question", "")), bool(row.get("is_multi_part")))
    retry_note = ""
    errors: list[str] = []
    started = time.time()
    for attempt in range(1, config.max_attempts + 1):
        try:
            result = client.complete(
                build_user_prompt(row, labels, retry_note),
                system_prompt=config.prompt,
                api_key=config.api_key,
            )
            answers, reasons = parse_and_verify(result.text, str(row["solution"]), labels)
            output = dict(row)
            # The source ground truths are intentionally untrusted and must not
            # survive into the extracted dataset.
            output.pop("final_answers", None)
            output.update(
                ground_truths=answers,
                null_answer_reasons=reasons,
                extraction_attempts=attempt,
                extraction_model=client.model,
                extraction_reasoning_effort=client.model_reasoning_effort,
                extraction_verification="ordered_content_tokens",
                extraction_seconds=round(time.time() - started, 3),
            )
            return index, output
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            errors.append(message)
            if isinstance(exc, ExtractionValidationError):
                retry_note = (
                    f"Your previous response failed deterministic verification: {exc}. Try again. "
                    "Successful answers may omit intervening material, but every retained word, "
                    "number, LaTeX command, and mathematical operator must come from SOLUTION "
                    "in its original order."
                )
            else:
                retry_note = "The previous extraction call failed. Try the extraction again."
    raise RowExtractionError(index, row, config.max_attempts, errors)


def failure_sidecar_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}_failures.jsonl")


def null_answers_sidecar_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}_null_answers.jsonl")


def collect_null_answers(input_path: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    null_answers = []
    for row in rows:
        answers = row.get("ground_truths", {})
        reasons = row.get("null_answer_reasons", {})
        labels = infer_part_labels(str(row.get("question", "")), bool(row.get("is_multi_part")))
        parts = sub_questions(str(row.get("question", "")), labels)
        for label in labels:
            if answers.get(label) is not None:
                continue
            null_answers.append(
                {
                    "dataset_id": rel_to_repo(input_path),
                    "sample_id": row.get("id"),
                    "source_file": row.get("source_file"),
                    "sub_part": label,
                    "question": row.get("question"),
                    "sub_question": parts[label],
                    "reason": reasons[label],
                }
            )
    return null_answers


def failed_row_record(input_path: Path, error: RowExtractionError) -> dict[str, Any]:
    row = error.row
    return {
        "dataset_id": rel_to_repo(input_path),
        "sample_id": row.get("id"),
        "source_file": row.get("source_file"),
        "question": row.get("question"),
        "attempts": error.attempts,
        "errors": error.errors,
    }


def rel_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def process_file(
    path: Path, args: argparse.Namespace, prompt: str
) -> tuple[Path, Path, int, Path, int]:
    rows = load_rows(path)
    if args.limit is not None:
        rows = rows[: args.limit]
    output_path = args.output_dir / path.name
    if output_path.exists() and not args.overwrite:
        raise FileExistsError(f"Output exists (use --overwrite): {output_path}")
    client = CodexLLM(
        model=args.model,
        model_reasoning_effort=args.model_reasoning_effort,
        codex_bin=args.codex_bin,
        timeout=args.timeout,
    )
    config = Config(prompt, args.api_key, args.max_extraction_attempts)
    completed: list[dict[str, Any] | None] = [None] * len(rows)
    failed_rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(extract_one, i, row, client, config): (i, row)
            for i, row in enumerate(rows)
        }
        for future in as_completed(futures):
            index, row = futures[future]
            try:
                _, output = future.result()
                completed[index] = output
                status = "ok"
            except RowExtractionError as exc:
                failed_rows.append(failed_row_record(path, exc))
                status = "failed"
            print(
                f"[{path.name}] {index + 1}/{len(rows)} {row.get('id', '')} {status}",
                flush=True,
            )
    output_rows = [row for row in completed if row is not None]
    null_answers = collect_null_answers(path, output_rows)
    write_rows(output_path, output_rows)
    failure_sidecar = failure_sidecar_path(output_path)
    failure_sidecar.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in failed_rows),
        encoding="utf-8",
    )
    null_sidecar = null_answers_sidecar_path(output_path)
    null_sidecar.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in null_answers),
        encoding="utf-8",
    )
    return output_path, failure_sidecar, len(failed_rows), null_sidecar, len(null_answers)


def main() -> int:
    args = parse_args()
    if args.workers < 1 or args.max_extraction_attempts < 1:
        raise ValueError("workers and max-extraction-attempts must be positive")
    prompt = args.prompt_file.read_text(encoding="utf-8").strip()
    for path in list_inputs(args.inputs, args.input_dir):
        output, failure_sidecar, failure_count, null_sidecar, null_count = process_file(
            path, args, prompt
        )
        print(f"Wrote {output}")
        print(f"Wrote {failure_sidecar} ({failure_count} failed row(s))")
        print(f"Wrote {null_sidecar} ({null_count} null answer(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
