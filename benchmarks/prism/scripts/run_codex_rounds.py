#!/usr/bin/env python3
"""Run resumable, successive Codex evaluations with PRISM's native grader."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import signal
import sys
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


PRISM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PRISM_ROOT.parents[1]
sys.path.insert(0, str(PRISM_ROOT))

from utils.data_utils import filter_and_convert  # noqa: E402
from utils.grade_utils import grade_problem_dag  # noqa: E402
from utils.prompt_utils import get_eval_prompt  # noqa: E402

_CODEX_LLM_PATH = REPO_ROOT / "utils" / "codex_cli" / "llm.py"
_CODEX_SPEC = importlib.util.spec_from_file_location("physics_codex_llm", _CODEX_LLM_PATH)
if _CODEX_SPEC is None or _CODEX_SPEC.loader is None:
    raise ImportError(f"Cannot load Codex wrapper from {_CODEX_LLM_PATH}")
_CODEX_MODULE = importlib.util.module_from_spec(_CODEX_SPEC)
sys.modules[_CODEX_SPEC.name] = _CODEX_MODULE
_CODEX_SPEC.loader.exec_module(_CODEX_MODULE)
CodexLLM = _CODEX_MODULE.CodexLLM


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=PRISM_ROOT / "datasets")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PRISM_ROOT / "results_codex" / "gpt-5.6-sol_high",
    )
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--grade-timeout", type=float, default=180.0)
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


@contextmanager
def grading_timeout(seconds: float):
    """Bound a native PRISM grade call so pathological CAS work cannot stall."""
    if seconds <= 0:
        yield
        return

    def handle_timeout(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"PRISM grading exceeded {seconds:g} seconds")

    previous = signal.signal(signal.SIGALRM, handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


def load_text_problems(data_dir: Path) -> list[dict[str, Any]]:
    problems: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(data_dir.glob("*_cleaned_dag.json")):
        for raw in json.loads(path.read_text()):
            if raw.get("images"):
                continue
            problem = filter_and_convert(raw)
            if not problem:
                continue
            pid = f"{path.stem}:{problem['id']}"
            if pid in seen:
                raise ValueError(f"Duplicate problem id: {pid}")
            seen.add(pid)
            problem["_eval_id"] = pid
            problem["_dataset_file"] = path.name
            problems.append(problem)
    return problems


def generate_one(
    problem: dict[str, Any], model: str, effort: str, timeout: float
) -> dict[str, Any]:
    llm = CodexLLM(
        model=model,
        model_reasoning_effort=effort,
        timeout=timeout,
        max_exec_retries=6,
        exec_retry_delay=10.0,
        strict_no_tools=True,
    )
    result = llm.complete(get_eval_prompt(problem))
    return {
        "problem_id": problem["_eval_id"],
        "response": result.text,
        "usage": result.usage,
        "attempts": result.attempts,
        "dataset_file": problem["_dataset_file"],
    }


def final_answer_result(problem: dict[str, Any], matches: list[dict]) -> dict[str, Any]:
    standard = problem["grading_standard"]
    if isinstance(standard, str):
        standard = json.loads(standard.replace("\\", "\\\\").replace(r"\\n", r"\n"))
    final_positions = [
        pos for pos, node in enumerate(standard) if node.get("is_final_answer", False)
    ]
    if not final_positions and standard:
        final_positions = [len(standard) - 1]
    matched_positions = {int(match["index_std"]) for match in matches}
    matched_finals = [pos for pos in final_positions if pos in matched_positions]
    return {
        "final_answer_correct": bool(final_positions)
        and len(matched_finals) == len(final_positions),
        "final_answer_score": (
            len(matched_finals) / len(final_positions) if final_positions else 0.0
        ),
        "final_formula_count": len(final_positions),
        "matched_final_formula_count": len(matched_finals),
    }


def grade_one(
    problem: dict[str, Any], response: dict[str, Any], timeout: float
) -> dict[str, Any]:
    with grading_timeout(timeout):
        score, matches = grade_problem_dag(problem, response["response"])
    grade = {
        "problem_id": problem["_eval_id"],
        "process_score": score,
        "matches": matches,
    }
    grade.update(final_answer_result(problem, matches))
    return grade


def summarize(round_number: int, attempted: int, grades: list[dict]) -> dict[str, Any]:
    n = len(grades)
    return {
        "round": round_number,
        "attempted": attempted,
        "graded": n,
        "process_score": sum(g["process_score"] for g in grades) / n if n else 0.0,
        "final_answer_accuracy": (
            sum(g["final_answer_correct"] for g in grades) / n if n else 0.0
        ),
        "solved_this_round": sum(g["final_answer_correct"] for g in grades),
    }


def main() -> int:
    args = parse_args()
    problems = load_text_problems(args.data_dir)
    if args.limit is not None:
        problems = problems[: args.limit]
    by_id = {problem["_eval_id"]: problem for problem in problems}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "rounds": args.rounds,
        "text_only_rule": "images is absent or empty",
        "solved_rule": "all PRISM DAG nodes marked is_final_answer match",
        "problem_count": len(problems),
        "problem_ids": list(by_id),
    }
    atomic_json(args.output_dir / "manifest.json", manifest)

    solved: set[str] = set()
    for prior_grade in sorted(args.output_dir.glob("round_*/grades/*.json")):
        grade = json.loads(prior_grade.read_text())
        if grade.get("final_answer_correct"):
            solved.add(str(grade["problem_id"]))
    summaries: list[dict[str, Any]] = []
    for round_number in range(1, args.rounds + 1):
        round_dir = args.output_dir / f"round_{round_number}"
        response_dir = round_dir / "responses"
        grade_dir = round_dir / "grades"
        response_dir.mkdir(parents=True, exist_ok=True)
        grade_dir.mkdir(parents=True, exist_ok=True)

        for old_grade in sorted(grade_dir.glob("*.json")):
            grade = json.loads(old_grade.read_text())
            if grade.get("final_answer_correct"):
                solved.add(str(grade["problem_id"]))

        pending = [problem for pid, problem in by_id.items() if pid not in solved]
        print(f"round {round_number}: {len(pending)} unsolved problems", flush=True)
        missing = [
            problem
            for problem in pending
            if not (response_dir / f"{problem['_eval_id'].replace(':', '__')}.json").exists()
        ]
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    generate_one,
                    problem,
                    args.model,
                    args.reasoning_effort,
                    args.timeout,
                ): problem
                for problem in missing
            }
            for future in as_completed(futures):
                problem = futures[future]
                try:
                    response = future.result()
                    filename = problem["_eval_id"].replace(":", "__") + ".json"
                    atomic_json(response_dir / filename, response)
                    print(f"generated {problem['_eval_id']}", flush=True)
                except Exception as exc:
                    print(f"generation failed {problem['_eval_id']}: {exc}", file=sys.stderr, flush=True)

        grades: list[dict[str, Any]] = []
        for problem in pending:
            filename = problem["_eval_id"].replace(":", "__") + ".json"
            response_path = response_dir / filename
            grade_path = grade_dir / filename
            if grade_path.exists():
                grade = json.loads(grade_path.read_text())
            elif response_path.exists():
                try:
                    grade = grade_one(
                        problem, json.loads(response_path.read_text()), args.grade_timeout
                    )
                    atomic_json(grade_path, grade)
                except TimeoutError as exc:
                    grade = {
                        "problem_id": problem["_eval_id"],
                        "process_score": 0.0,
                        "matches": [],
                        "final_answer_correct": False,
                        "final_answer_score": 0.0,
                        "final_formula_count": 0,
                        "matched_final_formula_count": 0,
                        "error": "grading_timeout",
                        "message": str(exc),
                    }
                    atomic_json(grade_path, grade)
                    print(f"grading timed out {problem['_eval_id']}", file=sys.stderr, flush=True)
                except Exception as exc:
                    print(f"grading failed {problem['_eval_id']}: {exc}", file=sys.stderr, flush=True)
                    continue
            else:
                continue
            grades.append(grade)
            if grade["final_answer_correct"]:
                solved.add(problem["_eval_id"])

        summary = summarize(round_number, len(pending), grades)
        summary["cumulative_solved"] = len(solved)
        summary["remaining"] = len(by_id) - len(solved)
        atomic_json(round_dir / "summary.json", summary)
        summaries.append(summary)
        atomic_json(args.output_dir / "summary.json", summaries)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
