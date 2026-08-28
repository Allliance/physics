#!/usr/bin/env python3
"""Score frozen filtered-Qwen PRISM responses across independent CPU workers."""

from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
PRISM_ROOT = REPO_ROOT / "benchmarks" / "prism"
RUNNER_PATH = PRISM_ROOT / "scripts" / "run_codex_rounds.py"
sys.path.insert(0, str(PRISM_ROOT))


def load_runner() -> Any:
    spec = importlib.util.spec_from_file_location("qwen_prism_round_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RUNNER = load_runner()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _grade_one_impl(task: tuple[dict[str, Any], str, float]) -> dict[str, Any]:
    problem, response, timeout = task
    from utils import grade_utils
    grade_utils.match_equations_parallel = grade_utils.match_equations
    started = time.monotonic()
    try:
        grade = RUNNER.grade_one(problem, {"response": response}, timeout)
        return {
            "id": problem["_eval_id"],
            "process_score": float(grade["process_score"]),
            "matches": grade["matches"],
            "correct": bool(grade["final_answer_correct"]),
            "final_answer_score": float(grade["final_answer_score"]),
            "final_formula_count": int(grade["final_formula_count"]),
            "matched_final_formula_count": int(grade["matched_final_formula_count"]),
            "grading_error": None,
            "grading_seconds": time.monotonic() - started,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {
            "id": problem["_eval_id"], "process_score": 0.0, "matches": [],
            "correct": False, "final_answer_score": 0.0,
            "final_formula_count": 0, "matched_final_formula_count": 0,
            "grading_error": f"{type(exc).__name__}: {exc}",
            "grading_seconds": time.monotonic() - started,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


def _grade_child(connection: Any, task: tuple[dict[str, Any], str, float]) -> None:
    try:
        connection.send(_grade_one_impl(task))
    finally:
        connection.close()


def grade_one(task: tuple[dict[str, Any], str, float]) -> dict[str, Any]:
    """Grade in a disposable child so a stuck symbolic comparison can be killed."""
    problem, _, timeout = task
    context = multiprocessing.get_context("fork")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_grade_child, args=(child, task))
    process.start()
    child.close()
    process.join(timeout + 5)
    if process.is_alive():
        process.terminate()
        process.join(2)
        if process.is_alive():
            process.kill()
            process.join()
        return {
            "id": problem["_eval_id"], "process_score": 0.0, "matches": [],
            "correct": False, "final_answer_score": 0.0,
            "final_formula_count": 0, "matched_final_formula_count": 0,
            "grading_error": f"TimeoutError: PRISM grading exceeded {timeout:g} seconds",
            "grading_seconds": timeout + 5,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    if parent.poll():
        return parent.recv()
    return {
        "id": problem["_eval_id"], "process_score": 0.0, "matches": [],
        "correct": False, "final_answer_score": 0.0,
        "final_formula_count": 0, "matched_final_formula_count": 0,
        "grading_error": f"WorkerExitError: grader exited with code {process.exitcode}",
        "grading_seconds": 0.0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--grade-timeout", type=float, default=180)
    args = parser.parse_args()
    affinity = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    workers = min(args.workers, affinity or 1)
    manifest = json.loads((args.artifact / "manifest.json").read_text(encoding="utf-8"))
    evaluated = set(map(str, manifest["evaluated_ids"]))
    generations = {str(item["id"]): item for item in read_jsonl(
        args.artifact / "generations.jsonl") if str(item["id"]) in evaluated}
    existing = {str(item["id"]): item for item in read_jsonl(args.artifact / "scores.jsonl")}
    problems = {item["_eval_id"]: item for item in RUNNER.load_text_problems(
        PRISM_ROOT / "datasets") if item["_eval_id"] in evaluated}
    missing_problem = set(generations) - set(problems)
    if missing_problem:
        raise ValueError(f"missing native problems: {sorted(missing_problem)[:5]}")
    pending = [item_id for item_id in generations if item_id not in existing]
    print(f"frozen={len(generations)} existing={len(existing)} pending={len(pending)} "
          f"workers={workers}", flush=True)
    output = args.artifact / "scores.jsonl"
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(grade_one, (problems[item_id], generations[item_id]["response"],
                                    args.grade_timeout)): item_id
            for item_id in pending
        }
        for completed, future in enumerate(as_completed(futures), 1):
            item = future.result()
            existing[item["id"]] = item
            with output.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
                handle.flush()
            if completed % 25 == 0 or completed == len(futures):
                errors = sum(bool(value.get("grading_error")) for value in existing.values())
                print(f"scored={completed}/{len(futures)} total={len(existing)} errors={errors}",
                      flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
