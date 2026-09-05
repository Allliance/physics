"""Prepare PRISM training data and UGPhysics validation data for verl."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
PRISM_ROOT = REPO_ROOT / "benchmarks" / "prism"
DEFAULT_OUTPUT = REPO_ROOT / "rlvr" / "data"
AUDIT_ROOT = REPO_ROOT / "audit" / "all-responses"

PRISM_SOURCE = "physics/prism"
UGPHYSICS_SOURCE = "physics/ugphysics"
def _load_function(path: Path, name: str) -> Callable[..., Any]:
    module_name = f"_rlvr_{path.stem}_{hashlib.sha1(str(path).encode()).hexdigest()[:8]}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return getattr(module, name)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _audited_failures(benchmark: str) -> set[str]:
    path = AUDIT_ROOT / benchmark / "responses.jsonl"
    return {
        str(row["problem_id"])
        for row in _read_jsonl(path)
        if (row.get("AI_audit") or {}).get("verdict") == "benchmark_failure"
    }


def _split_exact(
    rows: Iterable[tuple[str, dict[str, Any]]], validation_size: int, seed: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Select an exact-size, deterministic validation sample by hashed row ID."""
    ordered = sorted(rows, key=lambda item: item[0])
    if not 0 < validation_size < len(ordered):
        raise ValueError("validation_size must be positive and smaller than the dataset")
    validation_ids = {
        item_id
        for item_id, _row in sorted(
            ordered,
            key=lambda item: (hashlib.sha256(f"{seed}:{item[0]}".encode()).digest(), item[0]),
        )[:validation_size]
    }
    train: list[dict[str, Any]] = []
    validation: list[dict[str, Any]] = []
    for item_id, row in ordered:
        target = validation if item_id in validation_ids else train
        row["extra_info"]["split"] = "validation" if target is validation else "train"
        target.append(row)
    return train, validation


def _all_training(
    rows: Iterable[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    train = []
    for _item_id, row in sorted(rows, key=lambda item: item[0]):
        row["extra_info"]["split"] = "train"
        train.append(row)
    if not train:
        raise ValueError("training set is empty")
    return train


def _prism_rows(exclude_failures: bool) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, Any]]:
    filter_and_convert = _load_function(PRISM_ROOT / "utils" / "data_utils.py", "filter_and_convert")
    get_eval_prompt = _load_function(PRISM_ROOT / "utils" / "prompt_utils.py", "get_eval_prompt")
    excluded = _audited_failures("prism") if exclude_failures else set()
    rows: list[tuple[str, dict[str, Any]]] = []
    counts = {"raw": 0, "multimodal": 0, "native_filtered": 0, "audited_failure": 0}

    for path in sorted((PRISM_ROOT / "datasets").glob("*_cleaned_dag.json")):
        for raw in json.loads(path.read_text(encoding="utf-8")):
            counts["raw"] += 1
            if raw.get("images"):
                counts["multimodal"] += 1
                continue
            problem = filter_and_convert(copy.deepcopy(raw))
            if not problem:
                counts["native_filtered"] += 1
                continue
            item_id = f"{path.stem}:{problem['id']}"
            if item_id in excluded:
                counts["audited_failure"] += 1
                continue
            truth = {
                "benchmark": "prism",
                "problem_id": item_id,
                # The generative judge needs the full task and a worked reference,
                # rather than only the formula DAG consumed by PRISM's native
                # symbolic grader. Keep both representations so either reward can
                # use the same parquet files.
                "problem": get_eval_prompt(problem),
                "reference_answer": "\n\n".join(
                    str(subquestion["solution"])
                    for subquestion in problem["subquestions"]
                    if subquestion.get("solution")
                ),
                "grading_standard": problem["grading_standard"],
            }
            rows.append(
                (
                    item_id,
                    {
                        "data_source": PRISM_SOURCE,
                        "prompt": [{"role": "user", "content": get_eval_prompt(problem)}],
                        "ability": "physics",
                        "reward_model": {"style": "rule", "ground_truth": json.dumps(truth)},
                        "extra_info": {
                            "benchmark": "prism",
                            "problem_id": item_id,
                            "source_file": path.name,
                        },
                    },
                )
            )
    return rows, counts


def _ugphysics_rows(
    exclude_failures: bool,
) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, Any]]:
    """Collect the audited UGPhysics population directly from all-responses."""
    audit_path = AUDIT_ROOT / "ugphysics" / "responses.jsonl"
    audited = _read_jsonl(audit_path)
    if not audited:
        raise ValueError(f"UGPhysics audit source is empty or missing: {audit_path}")
    item_ids = [str(row["problem_id"]) for row in audited]
    if len(set(item_ids)) != len(item_ids):
        raise ValueError("UGPhysics audit source contains duplicate problem IDs")
    rows: list[tuple[str, dict[str, Any]]] = []
    counts = {"audit_source": len(audited), "audited_failure": 0}

    for row in audited:
        item_id = str(row["problem_id"])
        audit = row.get("AI_audit") or {}
        if exclude_failures and audit.get("verdict") == "benchmark_failure":
            counts["audited_failure"] += 1
            continue
        problem = str(row.get("problem_statement") or "").strip()
        reference = str(row.get("reference_solution") or "").strip()
        if not problem or not reference:
            raise ValueError(f"audited UGPhysics row lacks problem/reference text: {item_id}")
        truth = {
            "benchmark": "ugphysics",
            "problem_id": item_id,
            "problem": problem,
            "reference_answer": reference,
        }
        rows.append(
            (
                item_id,
                {
                    "data_source": UGPHYSICS_SOURCE,
                    "prompt": [{"role": "user", "content": problem}],
                    "ability": "physics",
                    "reward_model": {"style": "rule", "ground_truth": json.dumps(truth)},
                    "extra_info": {
                        "benchmark": "ugphysics",
                        "problem_id": item_id,
                        "subject": item_id.split("/", 1)[0],
                        "audit_verdict": audit.get("verdict") or "",
                    },
                },
            )
        )
    return rows, counts


def _write_dataset(
    name: str,
    rows: list[tuple[str, dict[str, Any]]],
    counts: dict[str, Any],
    output_root: Path,
    validation_size: int,
    seed: int,
    exclude_failures: bool,
) -> dict[str, Any]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    if validation_size:
        _unused, validation = _split_exact(rows, validation_size, seed)
        train = []
        split_strategy = "exact_sha256_validation_sample"
    else:
        train = _all_training(rows)
        validation = []
        split_strategy = "all_eligible_rows_are_training"
    output_dir = output_root / name
    output_dir.mkdir(parents=True, exist_ok=True)
    train_path = output_dir / "train.parquet"
    if train:
        pq.write_table(pa.Table.from_pylist(train), train_path, compression="zstd")
    else:
        train_path.unlink(missing_ok=True)
    validation_path = output_dir / "validation.parquet"
    if validation:
        pq.write_table(pa.Table.from_pylist(validation), validation_path, compression="zstd")
    else:
        # Never leave the obsolete held-out PRISM split looking usable.
        validation_path.unlink(missing_ok=True)
    manifest = {
        "benchmark": name,
        "seed": seed,
        "split_strategy": split_strategy,
        "requested_validation_rows": validation_size,
        "exclude_audited_benchmark_failures": exclude_failures,
        "train_rows": len(train),
        "validation_rows": len(validation),
        "counts": counts,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark", choices=("prism", "ugphysics", "all"), nargs="?", default="all")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--validation-size",
        type=int,
        default=200,
        help="Exact number of eligible UGPhysics rows to reserve for validation.",
    )
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument(
        "--include-audited-benchmark-failures",
        action="store_true",
        help="Keep rows marked benchmark_failure by the repository AI audit.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.validation_size <= 0:
        raise ValueError("--validation-size must be positive")
    args.output_root.mkdir(parents=True, exist_ok=True)
    exclude_failures = not args.include_audited_benchmark_failures
    manifests = []
    if args.benchmark in ("prism", "all"):
        rows, counts = _prism_rows(exclude_failures)
        manifests.append(
            _write_dataset(
                "prism", rows, counts, args.output_root, 0, args.seed, exclude_failures
            )
        )
    if args.benchmark in ("ugphysics", "all"):
        rows, counts = _ugphysics_rows(exclude_failures)
        manifests.append(
            _write_dataset(
                "ugphysics", rows, counts, args.output_root, args.validation_size, args.seed, exclude_failures
            )
        )
    print(json.dumps(manifests, indent=2))


if __name__ == "__main__":
    main()
