#!/usr/bin/env python3
"""Run Astra High on the corrected questions Astra Max missed in all four attempts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import time

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY))

from model_evals.astra.run_corrected_suite import (
    CMT_SOURCE,
    CRITPT_SOURCE,
    ROOT,
    build_inputs,
    file_hash,
    read_json,
    write_json,
)


ORDER = ("hle", "critpt", "cmt")
MODEL = "gpt-6-astra"
TAG = "astra-high-tools-on-max-unsolved-20260916"
MAX_SUMMARIES = {
    "hle": ROOT / "benchmarks/hle/artifacts/astra-max-tools-corrected-20260915/hle-corrected-tools.summary.json",
    "critpt": ROOT / "analysis/CritPt/artifacts/max-tools-four-rounds-20260907/gpt-6-astra-corrected.summary.json",
    "cmt": ROOT / "analysis/CMT-Benchmark/artifacts/astra-max-tools-corrected-20260915/cmt-corrected-tools.summary.json",
}
EXPECTED_COUNTS = {"hle": 12, "critpt": 4, "cmt": 3}


def build_target_ids(output: Path) -> dict[str, Path]:
    paths = {}
    for benchmark in ORDER:
        summary = read_json(MAX_SUMMARIES[benchmark])
        if not summary.get("complete") or summary.get("rounds") != 4:
            raise ValueError(f"Astra Max {benchmark} summary is incomplete")
        ids = [qid for qid, row in summary["per_question"].items()
               if row.get("round_scores") == [0, 0, 0, 0] and row.get("max") == 0]
        if len(ids) != EXPECTED_COUNTS[benchmark]:
            raise ValueError(f"Expected {EXPECTED_COUNTS[benchmark]} Max-unsolved {benchmark} IDs, found {len(ids)}")
        path = output / "inputs" / f"{benchmark}-max-pass4-zero-ids.json"
        if path.exists() and read_json(path) != ids:
            raise ValueError(f"Frozen target IDs changed: {path}")
        write_json(path, ids)
        paths[benchmark] = path
    return paths


def commands(output: Path, workers: int, hle_data: Path, ids: dict[str, Path]) -> dict[str, list[str]]:
    common = [
        "--model", MODEL, "--reasoning-effort", "high",
        "--judge-model", "claude-fable-5", "--judge-reasoning-effort", "high",
        "--use-tools", "--web-search", "live", "--rounds", "4",
        "--round-workers", "4", "--aggregation", "mean",
        "--num-workers", str(workers), "--timeout", "3600",
    ]
    return {
        "hle": [sys.executable, "-u", str(ROOT / "benchmarks/hle/evaluate.py"),
                "--dataset", str(hle_data), "--category", "Physics", "--no-include-images",
                "--ids-file", str(ids["hle"]), *common, "--limit-policy", "incorrect",
                "--output", str(ROOT / f"benchmarks/hle/artifacts/{TAG}/hle-max-unsolved.json")],
        "critpt": [sys.executable, "-u", str(ROOT / "analysis/CritPt/scripts/evaluate.py"),
                   "--dataset", str(CRITPT_SOURCE), "--ids-file", str(ids["critpt"]),
                   *common, "--limit-policy", "incorrect",
                   "--codex-bin", str(ROOT / "analysis/CritPt/scripts/codex_eval.py"),
                   "--output", str(ROOT / f"analysis/CritPt/artifacts/{TAG}/critpt-max-unsolved.json")],
        "cmt": [sys.executable, "-u", str(ROOT / "analysis/CMT-Benchmark/evaluate.py"),
                "--dataset", str(CMT_SOURCE), "--ids-file", str(ids["cmt"]), *common,
                "--output", str(ROOT / f"analysis/CMT-Benchmark/artifacts/{TAG}/cmt-max-unsolved.json")],
    }


def summary_path(command: list[str]) -> Path:
    return Path(command[command.index("--output") + 1]).with_suffix(".summary.json")


def report(output: Path, jobs: dict[str, list[str]]) -> dict:
    results = {}
    for benchmark in ORDER:
        path = summary_path(jobs[benchmark])
        row = read_json(path) if path.exists() else {"complete": False}
        complete = bool(row.get("complete"))
        results[benchmark] = {
            "complete": complete, "questions": row.get("questions"),
            "mean@4": row.get("mean_score") if complete else None,
            "pass@4": row.get("max_score") if complete else None,
            "round_scores": row.get("round_scores") if complete else None,
            "summary": str(path),
        }
    complete = all(row["complete"] for row in results.values())
    total_questions = sum(row["questions"] or 0 for row in results.values())
    total_correct = (sum(round(4 * row["questions"] * row["mean@4"])
                         for row in results.values()) if complete else None)
    total_passed = (sum(round(row["questions"] * row["pass@4"])
                        for row in results.values()) if complete else None)
    value = {
        "updated_at": datetime.now(timezone.utc).isoformat(), "complete": complete,
        "selection": "Astra Max pass@4 = 0 on the corrected benchmark",
        "model": MODEL, "reasoning_effort": "high", "tools": True, "web_search": "live",
        "judge_model": "claude-fable-5", "judge_reasoning_effort": "high",
        "attempts": 4, "order": list(ORDER), "results": results,
        "combined": {
            "questions": total_questions,
            "mean@4": total_correct / (4 * total_questions) if complete else None,
            "pass@4": total_passed / total_questions if complete else None,
            "correct_attempts": total_correct, "recovered_questions": total_passed,
        },
    }
    write_json(output / "summary.json", value)
    return value


def run_job(name: str, command: list[str], output: Path, retries: int) -> int:
    log = output / "logs" / f"{name}.log"
    for attempt in range(1, retries + 2):
        with log.open("a") as stream:
            stream.write(f"\nInvocation {attempt}: {json.dumps(command)}\n")
            stream.flush()
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode == 0:
            return 0
        if attempt <= retries:
            time.sleep(30)
    return result.returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / f"model_evals/astra/runs/{TAG}")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--stage", choices=["prepare", "all", "summary"], default="all")
    args = parser.parse_args(argv)
    if args.workers < 4 or args.retries < 0:
        parser.error("Workers must be at least four and retries nonnegative")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "logs").mkdir(exist_ok=True)
    with (output / ".suite.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        hle_data, _ = build_inputs(output)
        ids = build_target_ids(output)
        jobs = commands(output, args.workers, hle_data, ids)
        manifest = {
            "version": 1, "selection": "Astra Max pass@4 = 0", "model": MODEL,
            "reasoning_effort": "high", "tools": True, "web_search": "live",
            "judge_model": "claude-fable-5", "judge_effort": "high", "attempts": 4,
            "order": list(ORDER), "commands": jobs,
            "max_summary_sha256": {name: file_hash(path) for name, path in MAX_SUMMARIES.items()},
            "target_ids": {name: read_json(path) for name, path in ids.items()},
            "implementation_sha256": file_hash(Path(__file__)),
        }
        manifest_path = output / "manifest.json"
        if manifest_path.exists() and read_json(manifest_path) != manifest:
            raise ValueError("Targeted suite settings changed; choose a new output directory")
        write_json(manifest_path, manifest)
        current = report(output, jobs)
        if args.stage == "prepare":
            print(json.dumps(manifest, indent=2))
            return 0
        if args.stage == "summary":
            print(json.dumps(current, indent=2))
            return 0 if current["complete"] else 2
        for benchmark in ORDER:
            current = report(output, jobs)
            if current["results"][benchmark]["complete"]:
                continue
            print(f"Starting {benchmark}", flush=True)
            code = run_job(benchmark, jobs[benchmark], output, args.retries)
            current = report(output, jobs)
            if code or not current["results"][benchmark]["complete"]:
                print(f"{benchmark} remains pending; rerun to resume", flush=True)
                return 2
        final = report(output, jobs)
        print(json.dumps(final, indent=2), flush=True)
        return 0 if final["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
