#!/usr/bin/env python3
"""Build Kimi pre-audit results by reusing unchanged post-audit responses."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval.backends import validate_judgment
from eval.storage import atomic_json, file_hash, fingerprint


PYTHON = ROOT / "model_evals/fable/.venv/bin/python"
SOURCE = ROOT / "model_evals/kimi/runs/kimi-k3-max-no-tools-20260917/hle-corrected"
DEFAULT_OUTPUT = ROOT / "eval/artifacts/pre-audit-kimi-k3-max-reuse-20260918"
DATASETS = {
    "phybench": (ROOT / "eval/data/pre_audit/phybench.jsonl", "phybench"),
    "hle-physics": (ROOT / "eval/data/pre_audit/hle-physics.jsonl", "hle"),
    "prism": (ROOT / "eval/data/pre_audit/prism.jsonl", "prism"),
    "ugphysics": (ROOT / "eval/data/pre_audit/ugphysics.jsonl", "ugphysics"),
    "cmt": (ROOT / "eval/data/pre_audit/cmt.jsonl", "cmt"),
    "critpt": (ROOT / "eval/data/pre_audit/critpt.jsonl", "critpt"),
}
ATTEMPTS = (1, 2, 3, 4)


def read_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def command(output: Path, dataset: str, attempt: int, stage: str, workers: int) -> list[str]:
    data, _ = DATASETS[dataset]
    return [
        str(PYTHON), "-u", "-m", "eval", "post-audit",
        "--dataset", dataset,
        "--data", str(data),
        "--output", str(output / dataset / f"attempt-{attempt}"),
        "--model", "kimi-k3",
        "--judge-model", "gpt-5.6-sol",
        "--reasoning-effort", "max",
        "--judge-reasoning-effort", "high",
        "--mode", "merged",
        "--max-output-tokens", "65536",
        "--judge-max-output-tokens", "32768",
        "--timeout", "3600",
        "--workers", str(workers),
        "--stage", stage,
    ]


def run_jobs(output: Path, stage: str, parallel: int, workers: int) -> None:
    logs = output / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    def run_one(dataset: str, attempt: int) -> tuple[str, int, int]:
        argv = command(output, dataset, attempt, stage, workers)
        log = logs / f"{dataset}-attempt-{attempt}-{stage}.log"
        with log.open("a") as stream:
            stream.write(f"\n[{datetime.now(timezone.utc).isoformat()}]\n")
            stream.write(json.dumps(argv) + "\n")
            stream.flush()
            code = subprocess.run(
                argv, cwd=ROOT, env=os.environ, stdout=stream,
                stderr=subprocess.STDOUT,
            ).returncode
        if stage == "generate" and code == 0:
            directory = output / dataset / f"attempt-{attempt}"
            rows = read_json(directory / "dataset.json", [])
            predictions = read_json(directory / "predictions.json", {})
            if len(predictions) != len(rows):
                code = 2
        return dataset, attempt, code

    failed = []
    jobs = [(dataset, attempt) for dataset in DATASETS for attempt in ATTEMPTS]
    with ThreadPoolExecutor(max_workers=min(parallel, len(jobs))) as pool:
        futures = {pool.submit(run_one, *job): job for job in jobs}
        for future in as_completed(futures):
            dataset, attempt, code = future.result()
            print(f"{stage}: {dataset}/attempt-{attempt}: exit {code}", flush=True)
            if code:
                failed.append((dataset, attempt, code))
    atomic_json(output / f"{stage}-exit-codes.json", {
        f"{dataset}/attempt-{attempt}": code for dataset, attempt, code in failed
    })
    if failed:
        raise RuntimeError(f"{stage} failed for {failed}")


def validate_source_manifest(path: Path) -> None:
    manifest = read_json(path)
    if not isinstance(manifest, dict):
        raise ValueError(f"Missing source manifest: {path}")
    expected = {
        "model": "kimi-k3",
        "reasoning_effort": "max",
        "judge_model": "gpt-5.6-sol",
        "judge_reasoning_effort": "high",
        "tools": False,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"Source manifest mismatch for {key}: {path}")
    prompt_dir = ROOT / "eval/prompts"
    for name, digest in manifest.get("prompts_sha256", {}).items():
        current = prompt_dir / name
        if current.exists() and file_hash(current) != digest:
            raise ValueError(f"Prompt changed since source run: {current}")


def seed_reusable(output: Path) -> dict:
    report = {
        "version": 1,
        "policy": (
            "Reuse a post-audit response only when dataset ID and model-visible question "
            "text are byte-identical. Reuse its judgment only when the reference answer "
            "is also byte-identical and the saved prediction fingerprint matches."
        ),
        "source": str(SOURCE),
        "output": str(output),
        "attempts": {},
    }
    totals = {"questions": 0, "responses_reused": 0, "responses_to_generate": 0,
              "judgments_reused": 0, "judgments_to_run": 0}

    for dataset, (_, source_name) in DATASETS.items():
        for attempt in ATTEMPTS:
            target = output / dataset / f"attempt-{attempt}"
            source = SOURCE / source_name / f"attempt-{attempt}"
            validate_source_manifest(source / "manifest.json")
            target_rows = read_json(target / "dataset.json")
            source_rows = read_json(source / "dataset.json")
            source_predictions = read_json(source / "predictions.json")
            source_judgments = read_json(source / "judgments.json")
            if not all(isinstance(value, expected) for value, expected in (
                (target_rows, list), (source_rows, list),
                (source_predictions, dict), (source_judgments, dict),
            )):
                raise ValueError(f"Incomplete source/target artifacts: {dataset}/attempt-{attempt}")
            source_by_id = {str(row["id"]): row for row in source_rows}
            predictions = read_json(target / "predictions.json", {})
            judgments = read_json(target / "judgments.json", {})
            reused_responses = []
            reused_judgments = []
            generate_ids = []
            judge_ids = []

            for row in target_rows:
                qid = str(row["id"])
                old_row = source_by_id.get(qid)
                same_question = old_row is not None and old_row["question"] == row["question"]
                if same_question:
                    prediction = source_predictions[qid]
                    existing = predictions.get(qid)
                    if existing is not None and existing != prediction:
                        raise ValueError(f"Conflicting seeded prediction: {dataset}/{attempt}/{qid}")
                    predictions[qid] = prediction
                    reused_responses.append(qid)
                    same_reference = old_row.get("reference_answer") == row.get("reference_answer")
                    old_judgment = source_judgments.get(qid)
                    if same_reference and old_judgment is not None:
                        validate_judgment(old_judgment.get("judgment"))
                        if old_judgment.get("prediction_sha256") != fingerprint(prediction):
                            raise ValueError(f"Source judgment fingerprint mismatch: {dataset}/{attempt}/{qid}")
                        existing_judgment = judgments.get(qid)
                        if existing_judgment is not None and existing_judgment != old_judgment:
                            raise ValueError(f"Conflicting seeded judgment: {dataset}/{attempt}/{qid}")
                        judgments[qid] = old_judgment
                        reused_judgments.append(qid)
                    else:
                        judge_ids.append(qid)
                else:
                    generate_ids.append(qid)
                    judge_ids.append(qid)

            atomic_json(target / "predictions.json", predictions)
            atomic_json(target / "judgments.json", judgments)
            key = f"{dataset}/attempt-{attempt}"
            report["attempts"][key] = {
                "questions": len(target_rows),
                "responses_reused": len(reused_responses),
                "responses_to_generate": len(generate_ids),
                "judgments_reused": len(reused_judgments),
                "judgments_to_run": len(judge_ids),
                "reused_response_ids": reused_responses,
                "generated_response_ids": generate_ids,
                "reused_judgment_ids": reused_judgments,
                "new_judgment_ids": judge_ids,
            }
            totals["questions"] += len(target_rows)
            totals["responses_reused"] += len(reused_responses)
            totals["responses_to_generate"] += len(generate_ids)
            totals["judgments_reused"] += len(reused_judgments)
            totals["judgments_to_run"] += len(judge_ids)

    report["totals"] = totals
    atomic_json(output / "reuse-plan.json", report)
    print(json.dumps(totals, indent=2), flush=True)
    return report


def summarize(output: Path) -> dict:
    benchmarks = {}
    for dataset in DATASETS:
        attempt_rows = []
        canonical_ids = None
        by_id = {}
        complete = True
        for attempt in ATTEMPTS:
            directory = output / dataset / f"attempt-{attempt}"
            rows = read_json(directory / "dataset.json", [])
            predictions = read_json(directory / "predictions.json", {})
            judgments = read_json(directory / "judgments.json", {})
            ids = [str(row["id"]) for row in rows]
            if canonical_ids is None:
                canonical_ids = ids
                by_id = {qid: [] for qid in ids}
            elif ids != canonical_ids:
                raise ValueError(f"Attempt IDs differ for {dataset}")
            attempt_complete = set(predictions) == set(ids) and set(judgments) == set(ids)
            complete &= attempt_complete
            correct = 0
            for qid in ids:
                judgment = judgments.get(qid, {}).get("judgment")
                if judgment is None:
                    continue
                validate_judgment(judgment)
                value = judgment["correct"] == "yes"
                by_id[qid].append(value)
                correct += int(value)
            attempt_rows.append({
                "attempt": attempt,
                "complete": attempt_complete,
                "questions": len(ids),
                "correct": correct if attempt_complete else None,
                "accuracy": correct / len(ids) if attempt_complete else None,
            })
        n = len(canonical_ids or [])
        total_correct = sum(sum(values) for values in by_id.values())
        benchmarks[dataset] = {
            "questions": n,
            "complete": complete,
            "mean@4": total_correct / (4 * n) if complete else None,
            "pass@4": sum(any(values) for values in by_id.values()) / n if complete else None,
            "attempts": attempt_rows,
        }
    result = {
        "protocol": "pre-audit data with unified HLE-adapted evaluator",
        "model": "moonshotai/Kimi-K3",
        "reasoning_effort": "max",
        "judge_model": "gpt-5.6-sol",
        "judge_reasoning_effort": "high",
        "response_reuse": str(output / "reuse-plan.json"),
        "complete": all(value["complete"] for value in benchmarks.values()),
        "benchmarks": benchmarks,
    }
    atomic_json(output / "summary.json", result)
    print(json.dumps(result, indent=2), flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--stage", choices=("prepare", "generate", "judge", "summary", "all"),
                        default="all")
    parser.add_argument("--generation-parallel", type=int, default=12)
    parser.add_argument("--generation-workers", type=int, default=8)
    parser.add_argument("--judge-parallel", type=int, default=4)
    parser.add_argument("--judge-workers", type=int, default=4)
    args = parser.parse_args()
    if min(args.generation_parallel, args.generation_workers,
           args.judge_parallel, args.judge_workers) <= 0:
        parser.error("Worker counts must be positive")
    args.output.mkdir(parents=True, exist_ok=True)

    if args.stage in {"prepare", "all"}:
        run_jobs(args.output, "prepare", parallel=12, workers=1)
        seed_reusable(args.output)
    if args.stage in {"generate", "all"}:
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise RuntimeError("OPENROUTER_API_KEY is required for generation")
        run_jobs(args.output, "generate", args.generation_parallel, args.generation_workers)
    if args.stage in {"judge", "all"}:
        run_jobs(args.output, "judge", args.judge_parallel, args.judge_workers)
    result = summarize(args.output)
    return 0 if result["complete"] or args.stage in {"prepare", "generate"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
