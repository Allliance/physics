#!/usr/bin/env python3
"""Run Astra Max on corrected HLE, CritPt, and CMT in priority order."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
ORDER = ("hle", "critpt", "cmt")
MODEL = "gpt-6-astra"
TAG = "astra-max-tools-corrected-20260915"
HLE_AUDIT_SOURCE = ROOT / "audit/initial_data/all-responses/hle-physics/responses.jsonl"
AUDITS = ROOT / "audit/audits_processed.csv"
CMT_SOURCE = ROOT / "analysis/CMT-Benchmark/data/cmt_data_clean.json"
CRITPT_SOURCE = ROOT / "analysis/CritPt/corrected_challenge.jsonl"
CRITPT_RUN = (ROOT / "analysis/CritPt/artifacts/max-tools-four-rounds-20260907"
               / "gpt-6-astra-corrected")


def read_json(path: Path):
    return json.loads(path.read_text())


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_inputs(output: Path) -> tuple[Path, Path]:
    with AUDITS.open() as stream:
        audit_rows = list(csv.DictReader(stream))
    problem_failures = {
        row["source_problem_id"] for row in audit_rows
        if row["dataset"] == "hle-physics" and row["label"] == "PROBLEM_FAILURE"
    }
    source_rows = [json.loads(line) for line in HLE_AUDIT_SOURCE.read_text().splitlines() if line.strip()]
    if len(source_rows) != 202 or len(problem_failures) != 86:
        raise ValueError("Expected current HLE selection to contain 202 source rows and 86 problem failures")
    hle_rows = [
        {"id": row["problem_id"], "question": row["problem_statement"],
         "answer": row["reference_solution"], "category": "Physics", "image": ""}
        for row in source_rows if row["problem_id"] not in problem_failures
    ]
    if len(hle_rows) != 116 or len({row["id"] for row in hle_rows}) != 116:
        raise ValueError("Expected exactly 116 unique corrected HLE rows")

    cmt_rows = read_json(CMT_SOURCE)
    cmt_ids = [str(row["index"]) for row in cmt_rows if str(row["index"]) != "14"]
    if len(cmt_rows) != 50 or len(cmt_ids) != 49 or len(set(cmt_ids)) != 49:
        raise ValueError("Expected the corrected CMT selection to exclude only problem 14")

    inputs = output / "inputs"
    hle_path, cmt_ids_path = inputs / "hle-corrected-116.json", inputs / "cmt-corrected-49-ids.json"
    for path, value in ((hle_path, hle_rows), (cmt_ids_path, cmt_ids)):
        if path.exists() and read_json(path) != value:
            raise ValueError(f"Frozen input changed: {path}")
        write_json(path, value)
    return hle_path, cmt_ids_path


def verify_critpt() -> dict:
    sys.path.insert(0, str(ROOT / "analysis/CritPt/scripts"))
    from critpt_eval.dataset import load_dataset
    from critpt_eval.storage import fingerprint as critpt_fingerprint

    manifest = read_json(CRITPT_RUN.with_suffix(".run.json"))
    summary = read_json(CRITPT_RUN.with_suffix(".summary.json"))
    questions, answers, missing = load_dataset(CRITPT_SOURCE)
    expected = {
        "model": MODEL, "reasoning_effort": "max", "use_tools": True,
        "web_search": "live", "judge_model": "claude-fable-5",
        "judge_reasoning_effort": "high", "limit_policy": "incorrect",
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"Existing CritPt run has incompatible {key}: {manifest.get(key)!r}")
    if (missing or not summary.get("complete") or summary.get("questions") != 54 or
            manifest.get("question_ids") != [row["id"] for row in questions] or
            manifest.get("questions_sha256") != critpt_fingerprint(questions) or
            manifest.get("answers_sha256") != critpt_fingerprint(answers)):
        raise ValueError("Existing CritPt run no longer matches the current corrected 54-row dataset")
    return summary


def commands(output: Path, workers: int, hle_path: Path, cmt_ids_path: Path) -> dict[str, list[str]]:
    common = [
        "--model", MODEL, "--reasoning-effort", "max", "--judge-model", "claude-fable-5",
        "--judge-reasoning-effort", "high", "--use-tools", "--web-search", "live",
        "--rounds", "4", "--round-workers", "4", "--aggregation", "mean",
        "--num-workers", str(workers), "--timeout", "3600",
    ]
    return {
        "hle": [sys.executable, "-u", str(ROOT / "benchmarks/hle/evaluate.py"),
                "--dataset", str(hle_path), "--category", "Physics", "--no-include-images",
                *common, "--limit-policy", "incorrect",
                "--output", str(ROOT / f"benchmarks/hle/artifacts/{TAG}/hle-corrected-tools.json")],
        "cmt": [sys.executable, "-u", str(ROOT / "analysis/CMT-Benchmark/evaluate.py"),
                "--dataset", str(CMT_SOURCE), "--ids-file", str(cmt_ids_path), *common,
                "--output", str(ROOT / f"analysis/CMT-Benchmark/artifacts/{TAG}/cmt-corrected-tools.json")],
    }


def summary_path(benchmark: str, jobs: dict[str, list[str]]) -> Path:
    if benchmark == "critpt":
        return CRITPT_RUN.with_suffix(".summary.json")
    command = jobs[benchmark]
    return Path(command[command.index("--output") + 1]).with_suffix(".summary.json")


def report(output: Path, jobs: dict[str, list[str]]) -> dict:
    results = {}
    prior_complete = True
    for benchmark in ORDER:
        path = summary_path(benchmark, jobs)
        row = read_json(path) if path.exists() else {"complete": False}
        complete = bool(row.get("complete"))
        status = "complete" if complete else ("active/next" if prior_complete else "queued")
        results[benchmark] = {
            "complete": complete, "status": status, "questions": row.get("questions"),
            "mean@4": row.get("mean_score") if complete else None,
            "pass@4": row.get("max_score") if complete else None,
            "summary": str(path),
        }
        prior_complete = prior_complete and complete
    value = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "complete": all(row["complete"] for row in results.values()),
        "model": MODEL, "reasoning_effort": "max", "tools": True, "web_search": "live",
        "judge_model": "claude-fable-5", "judge_reasoning_effort": "high",
        "attempts": 4, "order": list(ORDER), "results": results,
    }
    write_json(output / "summary.json", value)
    lines = ["# GPT-6-Astra Max — corrected physics evaluations", "",
             "Tools and live search enabled for Astra; Fable 5 High judges without tools.", "",
             "| Benchmark | Questions | mean@4 | pass@4 | Status |",
             "|---|---:|---:|---:|---|"]
    for benchmark, row in results.items():
        mean = "—" if row["mean@4"] is None else f"{100 * row['mean@4']:.2f}%"
        passed = "—" if row["pass@4"] is None else f"{100 * row['pass@4']:.2f}%"
        lines.append(f"| {benchmark} | {row['questions'] or '—'} | {mean} | {passed} | {row['status']} |")
    lines.extend(["", f"Updated: {value['updated_at']}", ""])
    (output / "RESULTS.md.tmp").write_text("\n".join(lines))
    (output / "RESULTS.md.tmp").replace(output / "RESULTS.md")
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
    parser.add_argument("--workers", type=int, default=24)
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
        hle_path, cmt_ids_path = build_inputs(output)
        critpt = verify_critpt()
        jobs = commands(output, args.workers, hle_path, cmt_ids_path)
        manifest = {
            "version": 1, "model": MODEL, "reasoning_effort": "max", "tools": True,
            "web_search": "live", "judge_model": "claude-fable-5", "judge_effort": "high",
            "attempts": 4, "order": list(ORDER), "commands": jobs,
            "reused_critpt_summary": str(CRITPT_RUN.with_suffix(".summary.json")),
            "source_sha256": {str(path): file_hash(path) for path in
                              (AUDITS, HLE_AUDIT_SOURCE, CMT_SOURCE, CRITPT_SOURCE)},
            "implementation_sha256": file_hash(Path(__file__)),
        }
        manifest_path = output / "manifest.json"
        if manifest_path.exists() and read_json(manifest_path) != manifest:
            raise ValueError("Suite settings or frozen inputs changed; choose a new output directory")
        write_json(manifest_path, manifest)
        current = report(output, jobs)
        if args.stage == "prepare":
            print(json.dumps({"manifest": manifest, "critpt": {
                "questions": critpt["questions"], "mean@4": critpt["mean_score"],
                "pass@4": critpt["max_score"]}}, indent=2))
            return 0
        if args.stage == "summary":
            return 0 if current["complete"] else 2
        for benchmark in ORDER:
            current = report(output, jobs)
            if current["results"][benchmark]["complete"]:
                continue
            if benchmark == "critpt":
                raise ValueError("Validated CritPt run unexpectedly became incomplete")
            print(f"Starting {benchmark}", flush=True)
            code = run_job(benchmark, jobs[benchmark], output, args.retries)
            current = report(output, jobs)
            if code or not current["results"][benchmark]["complete"]:
                print(f"{benchmark} remains pending; rerun the same command to resume", flush=True)
                return 2
        return 0 if report(output, jobs)["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
