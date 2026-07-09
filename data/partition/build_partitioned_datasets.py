#!/usr/bin/env python3
"""Build partitioned Parquet datasets from repaired datasets and partition logs."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = REPO_ROOT / "repaired_datasets"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "partitioned_datasets"
DEFAULT_LABELS = REPO_ROOT / "scratch" / "multipart_analysis" / "final_question_part_labels.jsonl"
DEFAULT_PARTITIONS = REPO_ROOT / "scratch" / "multipart_analysis" / "messy_partition_full.jsonl"

QUESTION_FIELD_BY_DATASET = {
    "FrontierPhysics": "question",
    "Physics-TTT": "questions",
}
MULTI_LABELS = {"clean_multi_part", "messy_multi_part"}


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


def split_row_key(dataset: str, split: str, row_index: int, row: dict[str, Any]) -> tuple[str, str, int, str, str | None]:
    return (
        dataset,
        split,
        row_index,
        str(row.get("id")),
        row.get("source_file"),
    )


def load_labels(path: Path) -> dict[tuple[str, str, int, str, str | None], dict[str, Any]]:
    labels = {}
    for record in read_jsonl(path):
        labels[row_key(record)] = record
    return labels


def load_partitions(path: Path) -> dict[tuple[str, str, int, str, str | None], dict[str, Any]]:
    partitions = {}
    for record in read_jsonl(path):
        verified = (record.get("verification") or {}).get("passed")
        manual = bool(record.get("manual_review_passed"))
        if not verified and not manual:
            continue
        partitions[row_key(record)] = record
    return partitions


def output_row(
    *,
    dataset: str,
    split: str,
    row_index: int,
    row: dict[str, Any],
    label: dict[str, Any],
    partition: dict[str, Any] | None,
) -> dict[str, Any]:
    qfield = QUESTION_FIELD_BY_DATASET[dataset]
    final_label = label["final_label"]
    is_multi_part = final_label in MULTI_LABELS
    original_question = row.get(qfield)
    if not isinstance(original_question, str):
        raise ValueError(f"{dataset}/{split} row {row_index}: {qfield} is not a string")

    replacement = original_question
    unpartitioned_question: str | None = None
    if final_label == "messy_multi_part":
        if partition is None:
            raise ValueError(f"Missing passed partition for {dataset}/{split} row {row_index} id={row.get('id')}")
        replacement = partition["partitioned_question"]
        unpartitioned_question = original_question

    out: dict[str, Any] = {}
    inserted = False
    for key, value in row.items():
        if key == qfield:
            out[key] = replacement
            out["unpartitioned_question"] = unpartitioned_question
            out["is_multi_part"] = is_multi_part
            inserted = True
        else:
            out[key] = value
    if not inserted:
        out[qfield] = replacement
        out["unpartitioned_question"] = unpartitioned_question
        out["is_multi_part"] = is_multi_part
    return out


def build_split(
    path: Path,
    *,
    input_dir: Path,
    output_dir: Path,
    labels: dict[tuple[str, str, int, str, str | None], dict[str, Any]],
    partitions: dict[tuple[str, str, int, str, str | None], dict[str, Any]],
) -> dict[str, Any]:
    rel = path.relative_to(input_dir)
    dataset = path.parent.name
    split = path.name
    if dataset not in QUESTION_FIELD_BY_DATASET:
        raise ValueError(f"Unknown dataset directory: {dataset}")

    table = pq.read_table(path)
    rows = table.to_pylist()
    output_rows = []
    counts: Counter[str] = Counter()
    partitioned_count = 0
    for row_index, row in enumerate(rows):
        key = split_row_key(dataset, split, row_index, row)
        label = labels.get(key)
        if label is None:
            raise ValueError(f"Missing label for {dataset}/{split} row {row_index} id={row.get('id')}")
        partition = partitions.get(key)
        final_label = label["final_label"]
        counts[final_label] += 1
        if final_label == "messy_multi_part":
            partitioned_count += 1
        output_rows.append(
            output_row(
                dataset=dataset,
                split=split,
                row_index=row_index,
                row=row,
                label=label,
                partition=partition,
            )
        )

    output_path = output_dir / rel
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(output_rows), output_path)
    return {
        "path": str(rel),
        "input_rows": len(rows),
        "output_rows": len(output_rows),
        "partitioned_messy_multi_part": partitioned_count,
        "labels": dict(sorted(counts.items())),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--partitions", type=Path, default=DEFAULT_PARTITIONS)
    parser.add_argument("--summary", type=Path, default=REPO_ROOT / "scratch" / "multipart_analysis" / "partitioned_dataset_summary.json")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output_dir.exists():
        if not args.overwrite:
            print(f"{args.output_dir} already exists; pass --overwrite to replace it.", file=sys.stderr)
            return 2
        shutil.rmtree(args.output_dir)

    labels = load_labels(args.labels)
    partitions = load_partitions(args.partitions)
    summaries = []
    for path in sorted(args.input_dir.glob("*/*.parquet")):
        summary = build_split(
            path,
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            labels=labels,
            partitions=partitions,
        )
        summaries.append(summary)
        print(
            f"Wrote {summary['path']}: {summary['output_rows']} rows, "
            f"partitioned {summary['partitioned_messy_multi_part']}",
            flush=True,
        )

    total_rows = sum(item["output_rows"] for item in summaries)
    total_partitioned = sum(item["partitioned_messy_multi_part"] for item in summaries)
    label_counts: Counter[str] = Counter()
    for item in summaries:
        label_counts.update(item["labels"])
    result = {
        "input_dir": str(args.input_dir),
        "output_dir": str(args.output_dir),
        "total_rows": total_rows,
        "partitioned_messy_multi_part": total_partitioned,
        "labels": dict(sorted(label_counts.items())),
        "splits": summaries,
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
