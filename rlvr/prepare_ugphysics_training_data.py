"""Build cleaned UGPhysics RLVR splits and a final-only PRISM OOD split."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from rlvr.prepare_data import _prism_rows, _split_exact


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT = REPO_ROOT / "audit" / "all-responses" / "ugphysics" / "responses.jsonl"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ValueError(f"required JSONL does not exist: {path}")
    # Iterate physical JSONL records instead of using str.splitlines(), which
    # also splits on characters such as U+0085 embedded in valid JSON strings.
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verl_row(
    item_id: str,
    problem: str,
    reference: str,
    cleanup_source: str,
) -> tuple[str, dict[str, Any]]:
    truth = {
        "benchmark": "ugphysics",
        "problem_id": item_id,
        "problem": problem,
        "reference_answer": reference,
    }
    return (
        item_id,
        {
            "data_source": "physics/ugphysics",
            "prompt": [{"role": "user", "content": problem}],
            "ability": "physics",
            "reward_model": {"style": "rule", "ground_truth": json.dumps(truth)},
            "extra_info": {
                "benchmark": "ugphysics",
                "problem_id": item_id,
                "subject": item_id.split("/", 1)[0],
                "cleanup_source": cleanup_source,
            },
        },
    )


def collect_rows(
    audit_path: Path,
    sample_path: Path | None = None,
    judgments_path: Path | None = None,
) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, int]]:
    audited = _read_jsonl(audit_path)
    seed_rows: dict[str, tuple[str, dict[str, Any]]] = {}
    benchmark_failures = 0
    for row in audited:
        item_id = str(row["problem_id"])
        if (row.get("AI_audit") or {}).get("verdict") == "benchmark_failure":
            benchmark_failures += 1
            continue
        seed_rows[item_id] = _verl_row(
            item_id,
            str(row["problem_statement"]),
            str(row["reference_solution"]),
            "audited_seed_1000",
        )
    if len(seed_rows) + benchmark_failures != len(audited):
        raise ValueError("audited seed contains duplicate problem IDs")

    accepted_new: dict[str, tuple[str, dict[str, Any]]] = {}
    judged_new = 0
    rejected_new = 0
    if sample_path or judgments_path:
        if sample_path is None or judgments_path is None:
            raise ValueError("sample_path and judgments_path must be supplied together")
        sample = {str(row["_eval_id"]): row for row in _read_jsonl(sample_path)}
        judgments = {str(row["uid"]): row for row in _read_jsonl(judgments_path)}
        if len(sample) != len(_read_jsonl(sample_path)):
            raise ValueError("full sample contains duplicate IDs")
        for item_id, judgment in judgments.items():
            if item_id in seed_rows or any(str(row["problem_id"]) == item_id for row in audited):
                continue
            if judgment.get("status") != "completed":
                raise ValueError(f"judge result is incomplete for {item_id}")
            judged_new += 1
            if int(judgment["grade"]) != 1:
                rejected_new += 1
                continue
            row = sample[item_id]
            accepted_new[item_id] = _verl_row(
                item_id,
                str(row["problem"]),
                str(row["solution"]),
                "gpt56_sol_high_passed_qwen35_27b",
            )

    combined = {**seed_rows, **accepted_new}
    counts = {
        "audited_seed_rows": len(audited),
        "seed_benchmark_failures_excluded": benchmark_failures,
        "seed_rows_kept": len(seed_rows),
        "new_rows_judged": judged_new,
        "new_rows_rejected": rejected_new,
        "new_rows_kept": len(accepted_new),
        "combined_rows": len(combined),
    }
    return list(combined.values()), counts


def write_datasets(
    rows: list[tuple[str, dict[str, Any]]],
    output_root: Path,
    seed: int,
    validation_fraction: float,
    counts: dict[str, int],
    provenance: dict[str, str],
) -> dict[str, Any]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    if not 0.0 < validation_fraction < 1.0:
        raise ValueError("validation_fraction must be between zero and one")
    validation_size = max(1, round(len(rows) * validation_fraction))
    train, validation = _split_exact(rows, validation_size, seed)
    ug_dir = output_root / "ugphysics"
    ug_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(train), ug_dir / "train.parquet", compression="zstd")
    pq.write_table(
        pa.Table.from_pylist(validation),
        ug_dir / "validation.parquet",
        compression="zstd",
    )

    prism_rows, prism_counts = _prism_rows(exclude_failures=True)
    prism_validation = []
    for _item_id, row in sorted(prism_rows, key=lambda item: item[0]):
        row["extra_info"]["split"] = "validation"
        row["extra_info"]["evaluation_schedule"] = "final_only"
        prism_validation.append(row)
    prism_dir = output_root / "prism_ood"
    prism_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(prism_validation),
        prism_dir / "validation.parquet",
        compression="zstd",
    )

    manifest = {
        "seed": seed,
        "split_strategy": "deterministic_sha256_90_10",
        "validation_fraction": validation_fraction,
        "train_rows": len(train),
        "validation_rows": len(validation),
        "prism_ood_validation_rows": len(prism_validation),
        "prism_ood_schedule": "final_only",
        "counts": counts,
        "prism_counts": prism_counts,
        "provenance_sha256": provenance,
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--sample", type=Path)
    parser.add_argument("--judgments", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260904)
    parser.add_argument("--validation-fraction", type=float, default=0.1)
    args = parser.parse_args()

    rows, counts = collect_rows(args.audit, args.sample, args.judgments)
    provenance = {"audit": _sha256(args.audit)}
    if args.sample and args.judgments:
        provenance.update(
            {"sample": _sha256(args.sample), "judgments": _sha256(args.judgments)}
        )
    manifest = write_datasets(
        rows,
        args.output_root,
        args.seed,
        args.validation_fraction,
        counts,
        provenance,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
