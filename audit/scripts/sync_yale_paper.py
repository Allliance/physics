#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib==3.10.9"]
# ///
"""Validate processed audits, export aggregate results, and rebuild the Yale paper figure."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

AUDIT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PAPER = AUDIT_DIR.parent.parent / "yale-paper"
DATASETS = {"HLE": "hle-physics", "PHY": "phybench", "PRISM": "prism", "UG": "ugphysics"}
LABELS = {"PROBLEM_FAILURE": "problem", "GRADER_FAILURE": "grader", "MODEL_FAILURE": "model"}


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def collect_results(csv_path: Path, selected_dir: Path, template: dict) -> dict:
    """Join audits to the evaluated subset; require exactly one label per rejection."""
    csv_bytes = csv_path.read_bytes()
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig"), newline=""))
    fields = reader.fieldnames or []
    required = {"dataset", "source_problem_id", "label"}
    if not required.issubset(fields) or len(fields) != len(set(fields)):
        raise ValueError("CSV needs unique columns including dataset, source_problem_id, label")
    audits = {dataset: {} for dataset in DATASETS.values()}
    for number, row in enumerate(reader, start=2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Malformed CSV record {number}")
        dataset, problem_id, label = (row[field] for field in ("dataset", "source_problem_id", "label"))
        if dataset not in audits or label not in LABELS or not problem_id.strip():
            raise ValueError(f"Invalid dataset, problem ID, or label in CSV record {number}")
        if problem_id in audits[dataset]:
            raise ValueError(f"Duplicate/unresolved audit for {dataset}/{problem_id}")
        audits[dataset][problem_id] = label

    manifest_path = selected_dir / "selection-manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    data = copy.deepcopy(template)
    keys = Counter(row["key"] for row in data["benchmarks"])
    if not set(DATASETS).issubset(keys) or any(count != 1 for count in keys.values()):
        raise ValueError("Paper needs HLE, PHY, PRISM, UG and unique benchmark keys")
    response_hashes = {}
    for row in data["benchmarks"]:
        if row["key"] not in DATASETS:
            continue
        dataset = DATASETS[row["key"]]
        path = selected_dir / dataset / "responses.jsonl"
        content = path.read_bytes()
        entry = manifest["benchmarks"][dataset]
        if digest(content) != entry["selected_sha256"]:
            raise ValueError(f"Selection manifest hash mismatch for {dataset}")
        scores = {}
        for line in content.decode("utf-8").splitlines():
            if not line.strip():
                continue
            response = json.loads(line)
            problem_id = str(response["problem_id"])
            score = response["rule_based_binary_score"]
            if not problem_id or problem_id in scores or type(score) not in (int, float) or score not in (0, 1):
                raise ValueError(f"Invalid/duplicate evaluated item or nonbinary score in {dataset}")
            scores[problem_id] = int(score)
        rejected = {key for key, score in scores.items() if score == 0}
        if (len(scores) != entry["selected_count"]
                or set(scores) != set(entry["selected_problem_ids"])
                or len(rejected) != entry["selected_counts"]["unsolved"]
                or sum(scores.values()) != entry["selected_counts"]["solved"]):
            raise ValueError(f"Selection counts/IDs disagree with response records for {dataset}")
        if set(audits[dataset]) != rejected:
            missing = sorted(rejected - set(audits[dataset]))
            extra = sorted(set(audits[dataset]) - rejected)
            raise ValueError(f"Audit coverage mismatch for {dataset}: missing={missing}, extra={extra}")
        counts = Counter(audits[dataset].values())
        row.update(evaluated=len(scores), rejected=len(rejected), dataset=dataset,
                   **{field: counts[label] for label, field in LABELS.items()})
        if row["evaluated"] <= row["problem"]:
            raise ValueError(f"No retained items for {dataset}")
        row["scope"] = (f"{len(scores)} selected evaluation items; all {len(rejected)} initial "
                        "rejections matched to processed audit labels")
        response_hashes[dataset] = digest(content)

    data["status"] = "processed_audits_matched_to_evaluation"
    data["source"] = {
        "audit_csv_sha256": digest(csv_bytes),
        "selection_manifest_sha256": digest(manifest_bytes),
        "selected_responses_sha256": response_hashes,
        "validated_datasets": list(DATASETS.values()),
        "validation": "Item identities and coverage checked in the physics repository during sync; only aggregate results are exported.",
        "counting_rule": "One processed label per (dataset, source_problem_id); exact coverage of initial rejections.",
    }
    data["assumptions"] = [
        "Processed labels include the audit pipeline's selected reviews and manual overrides; matching records does not independently verify their scientific correctness.",
        "Initially accepted responses are retained as correct on valid questions; they were not independently audited.",
        "Initial scores and denominators come from the selected response exports; evaluation protocols can differ across benchmarks.",
        "The model name is retained from the paper configuration; the exports do not establish an exact model snapshot or settings.",
    ]
    return data


def sync(csv_path: Path, selected_dir: Path, paper: Path, build_paper: bool = True) -> dict:
    template = json.loads((paper / "results/audit_counts.json").read_text())
    data = collect_results(csv_path, selected_dir, template)
    # Generate in isolation so validation/plotting failures leave published assets intact.
    with tempfile.TemporaryDirectory(prefix="yale-audit-") as directory:
        staging = Path(directory)
        for folder in ("code", "results", "tables", "figures"):
            shutil.copytree(paper / folder, staging / folder)
        (staging / "results/audit_counts.json").write_text(json.dumps(data, indent=2) + "\n")
        subprocess.run([sys.executable, str(staging / "code/build_audit_results.py"),
                        "--refresh-accuracy"], check=True)
        for extension in ("pdf", "png"):
            subprocess.run([sys.executable, str(staging / "code/plot_benchmark_accuracy.py"),
                            "--output", str(staging / f"figures/benchmark_accuracy.{extension}")], check=True)
        outputs = [
            "results/audit_counts.json",
            "results/audit_derived.json", "results/audit_numbers.tex", "results/accuracy.json",
            "tables/accuracy_tabular.tex", "tables/attribution_tabular.tex", "tables/attribution_rows.tex",
            "figures/benchmark_accuracy.pdf", "figures/benchmark_accuracy.png",
        ]
        for relative in outputs:
            shutil.copyfile(staging / relative, paper / relative)
    if build_paper:
        subprocess.run(["make", "pdf", f"PYTHON={sys.executable}"], cwd=paper, check=True)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=AUDIT_DIR / "audits_processed.csv")
    parser.add_argument("--selected-dir", type=Path, default=AUDIT_DIR / "initial_data/selected")
    parser.add_argument("--paper-dir", type=Path, default=DEFAULT_PAPER)
    parser.add_argument("--skip-paper-build", action="store_true", help="Update data and figures without running make pdf")
    args = parser.parse_args()
    try:
        data = sync(args.input.resolve(), args.selected_dir.resolve(), args.paper_dir.resolve(), not args.skip_paper_build)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Sync failed: {error}\n")
    total = sum(row["rejected"] for row in data["benchmarks"])
    print(f"Synced {total} audited items to {args.paper_dir.resolve()}")
    for row in data["benchmarks"]:
        print(f"{row['name']}: {row['problem']} problem, {row['grader']} grader, {row['model']} model failures")


if __name__ == "__main__":
    main()
