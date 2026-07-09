#!/usr/bin/env python3
"""Partition messy multi-part questions into explicit clean multi-part text.

The script reads labels produced by scratch/multipart_analysis and processes
only rows labeled `messy_multi_part`. It writes append-only JSONL checkpoints
containing the original question, partitioned question, and content-preservation
verification metrics.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.codex_cli import CodexLLM  # noqa: E402


DEFAULT_LABELS = REPO_ROOT / "scratch" / "multipart_analysis" / "final_question_part_labels.jsonl"
DEFAULT_PROMPT = REPO_ROOT / "data" / "partition" / "partition_prompt.txt"
DEFAULT_OUTPUT = REPO_ROOT / "scratch" / "multipart_analysis" / "messy_partition_smoke.jsonl"

PART_LABEL_RE = re.compile(r"(?m)^\s*\([a-z]\)\s*")
TOKEN_RE = re.compile(r"\\[A-Za-z]+|[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:\.\d+)?|[^\s]")
MULTISPACE_RE = re.compile(r"\s+")
STYLE_TOKENS = {
    "a",
    "an",
    "and",
    "as",
    "by",
    "calculate",
    "determine",
    "evaluate",
    "find",
    "following",
    "for",
    "give",
    "in",
    "of",
    "or",
    "the",
    "to",
    "what",
}


@dataclass
class PartitionResult:
    index: int
    record: dict[str, Any]


def compact(text: Any) -> str:
    return MULTISPACE_RE.sub(" ", str(text or "").replace("\ufeff", "")).strip()


def normalize_for_compare(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\ufeff", "")
    text = PART_LABEL_RE.sub("", text)
    text = re.sub(r"(?<!\w)\([a-z]\)\s*", "", text)
    text = MULTISPACE_RE.sub(" ", text).strip().casefold()
    return text


def tokens_for_compare(text: str) -> list[str]:
    normalized = normalize_for_compare(text)
    return TOKEN_RE.findall(normalized)


def content_tokens_for_compare(text: str) -> list[str]:
    return [
        token
        for token in tokens_for_compare(text)
        if re.search(r"[A-Za-z0-9\\]", token) and token not in STYLE_TOKENS
    ]


def multiset_jaccard(left: list[str], right: list[str]) -> float:
    a = Counter(left)
    b = Counter(right)
    if not a and not b:
        return 1.0
    intersection = sum((a & b).values())
    union = sum((a | b).values())
    return intersection / union if union else 1.0


def fraction_missing(original: list[str], candidate: list[str]) -> float:
    orig = Counter(original)
    cand = Counter(candidate)
    if not orig:
        return 0.0
    missing = sum((orig - cand).values())
    return missing / sum(orig.values())


def fraction_added(original: list[str], candidate: list[str]) -> float:
    orig = Counter(original)
    cand = Counter(candidate)
    if not cand:
        return 0.0
    added = sum((cand - orig).values())
    return added / sum(cand.values())


def detected_part_labels(text: str) -> list[str]:
    return re.findall(r"(?m)^\s*\(([a-z])\)\s+", text)


def new_doubled_latex_commands(original: str, partitioned: str) -> list[str]:
    original_doubled = Counter(re.findall(r"\\\\[A-Za-z]+", original))
    partitioned_doubled = Counter(re.findall(r"\\\\[A-Za-z]+", partitioned))
    return list((partitioned_doubled - original_doubled).elements())


def labels_are_consecutive(labels: list[str]) -> bool:
    if len(labels) < 2:
        return False
    expected = [chr(ord("a") + i) for i in range(len(labels))]
    return labels == expected


def verify_partition(original: str, partitioned: str) -> dict[str, Any]:
    original_norm = normalize_for_compare(original)
    partitioned_norm = normalize_for_compare(partitioned)
    original_tokens = tokens_for_compare(original)
    partitioned_tokens = tokens_for_compare(partitioned)
    original_content_tokens = content_tokens_for_compare(original)
    partitioned_content_tokens = content_tokens_for_compare(partitioned)
    labels = detected_part_labels(partitioned)
    doubled_latex = new_doubled_latex_commands(original, partitioned)

    char_similarity = SequenceMatcher(None, original_norm, partitioned_norm).ratio()
    token_jaccard = multiset_jaccard(original_tokens, partitioned_tokens)
    missing = fraction_missing(original_tokens, partitioned_tokens)
    added = fraction_added(original_tokens, partitioned_tokens)
    content_jaccard = multiset_jaccard(original_content_tokens, partitioned_content_tokens)
    content_missing = fraction_missing(original_content_tokens, partitioned_content_tokens)
    content_added = fraction_added(original_content_tokens, partitioned_content_tokens)
    length_ratio = (
        len(partitioned_norm) / len(original_norm)
        if original_norm
        else math.inf if partitioned_norm else 1.0
    )
    label_count = len(labels)
    consecutive = labels_are_consecutive(labels)

    passed = (
        label_count >= 2
        and consecutive
        and token_jaccard >= 0.80
        and missing <= 0.12
        and added <= 0.16
        and content_jaccard >= 0.92
        and content_missing <= 0.06
        and content_added <= 0.08
        and 0.75 <= length_ratio <= 1.35
        and not doubled_latex
    )
    return {
        "passed": passed,
        "part_labels": labels,
        "label_count": label_count,
        "labels_consecutive": consecutive,
        "char_similarity": round(char_similarity, 4),
        "token_multiset_jaccard": round(token_jaccard, 4),
        "missing_token_fraction": round(missing, 4),
        "added_token_fraction": round(added, 4),
        "content_token_multiset_jaccard": round(content_jaccard, 4),
        "missing_content_token_fraction": round(content_missing, 4),
        "added_content_token_fraction": round(content_added, 4),
        "length_ratio_without_labels": round(length_ratio, 4),
        "new_doubled_latex_commands": doubled_latex,
        "thresholds": {
            "min_label_count": 2,
            "labels_must_be_consecutive": True,
            "min_token_multiset_jaccard": 0.80,
            "max_missing_token_fraction": 0.12,
            "max_added_token_fraction": 0.16,
            "min_content_token_multiset_jaccard": 0.92,
            "max_missing_content_token_fraction": 0.06,
            "max_added_content_token_fraction": 0.08,
            "length_ratio_without_labels": [0.75, 1.35],
            "new_doubled_latex_commands_allowed": False,
        },
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def row_key(record: dict[str, Any]) -> tuple[str, str, int, str, str | None]:
    return (
        record["dataset"],
        record["split"],
        int(record["row_index"]),
        str(record["id"]),
        record.get("source_file"),
    )


def load_existing(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    retry_failed: bool = False,
) -> list[PartitionResult | None]:
    results: list[PartitionResult | None] = [None] * len(rows)
    if not path.exists():
        return results
    expected = {row_key(row): i for i, row in enumerate(rows)}
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                print(f"Skipping malformed checkpoint line {line_number}", file=sys.stderr)
                continue
            key = (
                record.get("dataset"),
                record.get("split"),
                int(record.get("row_index", -1)),
                str(record.get("id")),
                record.get("source_file"),
            )
            index = expected.get(key)
            if index is not None and record.get("partitioned_question"):
                if retry_failed and not (record.get("verification") or {}).get("passed"):
                    continue
                results[index] = PartitionResult(index=index, record=record)
    return results


def ensure_append_boundary(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        return
    with path.open("rb+") as f:
        f.seek(-1, os.SEEK_END)
        if f.read(1) != b"\n":
            f.write(b"\n")


def build_user_prompt(record: dict[str, Any]) -> str:
    return (
        "Convert this messy multi-part physics question into a clean multi-part "
        "question by adding labels and line breaks only.\n\n"
        f"Dataset: {record['dataset']}\n"
        f"Split: {record['split']}\n"
        f"Row index: {record['row_index']}\n"
        f"ID: {record['id']}\n"
        f"Source file: {record.get('source_file')}\n\n"
        "Question text begins after this line. Copy LaTeX backslashes exactly; "
        "the text is not JSON and backslashes are literal.\n\n"
        f"{record['question']}"
    )


def partition_one(
    index: int,
    record: dict[str, Any],
    *,
    system_prompt: str,
    model: str,
    reasoning_effort: str,
    timeout: float,
    codex_bin: str,
    api_key: str | None,
) -> PartitionResult:
    started = time.time()
    client = CodexLLM(
        model=model,
        model_reasoning_effort=reasoning_effort,
        codex_bin=codex_bin,
        timeout=timeout,
        strict_no_tools=True,
        max_tool_retries=3,
        max_exec_retries=6,
        exec_retry_delay=10.0,
    )
    llm_result = client.complete(
        build_user_prompt(record),
        system_prompt=system_prompt,
        api_key=api_key,
    )
    partitioned = llm_result.text.strip()
    verification = verify_partition(record["question"], partitioned)
    output = {
        "dataset": record["dataset"],
        "split": record["split"],
        "row_index": record["row_index"],
        "source_file": record.get("source_file"),
        "domain": record.get("domain"),
        "id": record["id"],
        "question_field": record.get("question_field"),
        "original_label": record.get("final_label"),
        "original_question": record["question"],
        "partitioned_question": partitioned,
        "verification": verification,
        "latency_seconds": round(time.time() - started, 3),
        "model": model,
        "model_reasoning_effort": reasoning_effort,
    }
    if llm_result.usage is not None:
        output["usage"] = llm_result.usage
    return PartitionResult(index=index, record=output)


def append_result(handle: Any, result: PartitionResult) -> None:
    handle.write(json.dumps(result.record, ensure_ascii=False) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def print_progress(result: PartitionResult, completed: int, total: int) -> None:
    record = result.record
    verification = record["verification"]
    status = "pass" if verification["passed"] else "FAIL"
    print(
        f"[{completed}/{total}] {status} "
        f"{record['dataset']}/{record['split']} row={record['row_index']} "
            f"id={record['id']} labels={verification['part_labels']} "
            f"jaccard={verification['token_multiset_jaccard']} "
            f"content_jaccard={verification['content_token_multiset_jaccard']} "
            f"missing={verification['missing_token_fraction']} "
            f"added={verification['added_token_fraction']} "
            f"doubled_latex={verification['new_doubled_latex_commands']}",
        flush=True,
    )


def select_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    rows = [row for row in read_jsonl(args.labels) if row.get("final_label") == "messy_multi_part"]
    if args.examples:
        wanted = set(args.examples)
        rows = [
            row
            for row in rows
            if f"{row['dataset']}/{row['split']}:{row['id']}" in wanted
            or f"{row['dataset']}:{row['id']}" in wanted
            or str(row["id"]) in wanted
        ]
    if args.limit is not None:
        rows = rows[: args.limit]
    return rows


def write_review_markdown(path: Path, results: list[PartitionResult]) -> None:
    lines = ["# Messy Partition Smoke Review", ""]
    for result in results:
        record = result.record
        verification = record["verification"]
        lines.append(
            "## "
            f"{record['dataset']}/{record['split']} row={record['row_index']} "
            f"id={record['id']}"
        )
        lines.append("")
        lines.append(f"Verification passed: `{verification['passed']}`")
        lines.append(
            "Metrics: "
            f"jaccard={verification['token_multiset_jaccard']}, "
            f"content_jaccard={verification['content_token_multiset_jaccard']}, "
            f"missing={verification['missing_token_fraction']}, "
            f"added={verification['added_token_fraction']}, "
            f"length_ratio={verification['length_ratio_without_labels']}, "
            f"doubled_latex={verification['new_doubled_latex_commands']}"
        )
        lines.append("")
        lines.append("Original:")
        lines.append("")
        lines.append("```text")
        lines.append(record["original_question"])
        lines.append("```")
        lines.append("")
        lines.append("Partitioned:")
        lines.append("")
        lines.append("```text")
        lines.append(record["partitioned_question"])
        lines.append("```")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--review-md",
        type=Path,
        default=REPO_ROOT / "scratch" / "multipart_analysis" / "messy_partition_smoke_review.md",
    )
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--model-reasoning-effort", default="high")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--examples", nargs="*", help="Specific ids or dataset/split:id keys")
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Ignore existing checkpoint entries whose verification did not pass.",
    )
    parser.add_argument("--codex-bin", default=os.getenv("CODEX_BIN", "codex"))
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--api-key", default=os.getenv("CODEX_API_KEY"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.workers < 1:
        print("--workers must be at least 1", file=sys.stderr)
        return 2

    rows = select_rows(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    system_prompt = args.prompt.read_text(encoding="utf-8")
    results = load_existing(args.output, rows, retry_failed=args.retry_failed)
    existing = sum(item is not None for item in results)
    pending = [(i, row) for i, row in enumerate(rows) if results[i] is None]
    print(
        f"Partitioning {len(pending)} pending row(s) "
        f"({existing}/{len(rows)} already done) with workers={args.workers}",
        flush=True,
    )

    ensure_append_boundary(args.output)
    with args.output.open("a", encoding="utf-8") as out:
        if args.workers == 1:
            completed = existing
            for index, row in pending:
                result = partition_one(
                    index,
                    row,
                    system_prompt=system_prompt,
                    model=args.model,
                    reasoning_effort=args.model_reasoning_effort,
                    timeout=args.timeout,
                    codex_bin=args.codex_bin,
                    api_key=args.api_key,
                )
                results[index] = result
                append_result(out, result)
                completed += 1
                print_progress(result, completed, len(rows))
        elif pending:
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {
                    executor.submit(
                        partition_one,
                        index,
                        row,
                        system_prompt=system_prompt,
                        model=args.model,
                        reasoning_effort=args.model_reasoning_effort,
                        timeout=args.timeout,
                        codex_bin=args.codex_bin,
                        api_key=args.api_key,
                    ): index
                    for index, row in pending
                }
                completed = existing
                for future in as_completed(futures):
                    result = future.result()
                    results[result.index] = result
                    append_result(out, result)
                    completed += 1
                    print_progress(result, completed, len(rows))

    completed_results = [item for item in results if item is not None]
    if len(completed_results) != len(rows):
        raise RuntimeError("Internal error: missing partition results")
    write_review_markdown(args.review_md, completed_results)
    passed = sum(item.record["verification"]["passed"] for item in completed_results)
    print(f"Verification passed {passed}/{len(completed_results)} row(s)", flush=True)
    print(f"Wrote review markdown to {args.review_md}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
