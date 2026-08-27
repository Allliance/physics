"""Run the supplied PHYSICS SymPy scorer without an LLM fallback."""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any


BENCHMARK_ROOT = Path(__file__).parent
REPO_ROOT = BENCHMARK_ROOT.parents[1]
API_EVALUATION = BENCHMARK_ROOT / "api_evaluation"
if str(API_EVALUATION) not in sys.path:
    sys.path.insert(0, str(API_EVALUATION))

import equation_equivilancy  # noqa: E402
import extract_boxed  # noqa: E402


DEFAULT_DATASET = (
    BENCHMARK_ROOT / "PHYSICS" / "PHYSICS-textonly" / "physics_textonly.jsonl"
)
DEFAULT_RESPONSES = (
    REPO_ROOT
    / "audit"
    / "all-responses"
    / "PHYSICS"
    / "gpt-5.6-sol-high.jsonl"
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "audit" / "audit-data" / "PHYSICS" / "gpt-5.6-sol-high"
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    temp_path.replace(path)


def extract_answers(response: str | None) -> list[str]:
    if not response:
        return []
    extracted = extract_boxed.extract_final_answer_allform(response, answer_type="list")
    if not extracted:
        return []
    if isinstance(extracted[0], list):
        return [item for group in extracted for item in group]
    return extracted


def sympy_evaluate(
    candidate_answers: list[str], reference_answers: list[str]
) -> tuple[float, list[dict[str, Any]], list[int]]:
    comparisons: list[dict[str, Any]] = []
    unmatched: list[int] = []
    correct_count = 0

    for candidate_index, candidate in enumerate(candidate_answers):
        matched = False
        for reference_index, reference in enumerate(reference_answers):
            result = equation_equivilancy.is_equiv(
                candidate,
                reference,
                verbose=False,
                use_llm_fallback=False,
            )
            comparison = {
                "candidate_index": candidate_index,
                "reference_index": reference_index,
                **result,
            }
            comparisons.append(comparison)
            if result["sympy_result"] is True:
                correct_count += 1
                matched = True
                break
        if not matched:
            unmatched.append(candidate_index)

    score = correct_count / len(candidate_answers) if candidate_answers else 0.0
    return score, comparisons, unmatched


def evaluate_row(
    index: int,
    source_row: dict[str, Any],
    response_row: dict[str, Any] | None,
) -> tuple[int, dict[str, Any], list[int]]:
    if response_row is None:
        response_row = {}
        generation_status = "missing"
    elif not response_row.get("llm_answers"):
        generation_status = "failed"
    else:
        generation_status = "completed"

    candidate_answers = extract_answers(response_row.get("llm_answers"))
    reference_answers = source_row.get("final_answers", [])
    sympy_score, comparisons, unmatched = sympy_evaluate(
        candidate_answers, reference_answers
    )
    if generation_status != "completed":
        judge_status = "generation_unavailable"
    elif not candidate_answers:
        judge_status = "no_extracted_answers"
    elif unmatched:
        judge_status = "not_run"
    else:
        judge_status = "not_needed"

    result = {
        "id": source_row["id"],
        "model": response_row.get("model"),
        "reasoning_effort": response_row.get("reasoning_effort"),
        "generation_status": generation_status,
        "generation_error": response_row.get("generation_error"),
        "candidate_answers": candidate_answers,
        "reference_answers": reference_answers,
        "sympy_score": sympy_score,
        "sympy_accepted": bool(candidate_answers) and not unmatched,
        "sympy_comparisons": comparisons,
        "judge_status": judge_status,
        "judgments": None,
        "combined_score": None,
    }
    return index, result, unmatched


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--responses", type=Path, default=DEFAULT_RESPONSES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--workers", type=int, default=16)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset = read_jsonl(args.dataset)
    response_by_id = {row["id"]: row for row in read_jsonl(args.responses)}
    missing = [row["id"] for row in dataset if row["id"] not in response_by_id]
    if missing:
        print(
            f"Missing {len(missing)} responses; they will score as zero. "
            f"First missing id: {missing[0]}",
            flush=True,
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    evaluation_path = args.output_dir / "evaluation.jsonl"
    indexed_results: dict[int, tuple[dict[str, Any], list[int]]] = {}
    work = [
        (index, source_row, response_by_id.get(source_row["id"]))
        for index, source_row in enumerate(dataset)
    ]
    if args.workers == 1:
        completed_rows = (evaluate_row(*item) for item in work)
        for completed, (index, result, unmatched) in enumerate(completed_rows, start=1):
            indexed_results[index] = (result, unmatched)
            if completed % 25 == 0 or completed == len(dataset):
                print(f"evaluated={completed}/{len(dataset)}", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(evaluate_row, *item) for item in work]
            for completed, future in enumerate(as_completed(futures), start=1):
                index, result, unmatched = future.result()
                indexed_results[index] = (result, unmatched)
                if completed % 25 == 0 or completed == len(dataset):
                    print(f"evaluated={completed}/{len(dataset)}", flush=True)

    results = [indexed_results[index][0] for index in range(len(dataset))]
    write_jsonl(evaluation_path, results)

    sympy_accuracy = sum(row["sympy_score"] for row in results) / len(results)
    completed_results = [
        row for row in results if row["generation_status"] == "completed"
    ]
    sympy_accuracy_completed = (
        sum(row["sympy_score"] for row in completed_results) / len(completed_results)
    )
    summary = {
        "dataset": str(args.dataset.relative_to(REPO_ROOT)),
        "responses": str(args.responses.relative_to(REPO_ROOT)),
        "problem_count": len(results),
        "completed_generation_count": len(completed_results),
        "failed_generation_count": sum(
            row["generation_status"] == "failed" for row in results
        ),
        "missing_generation_count": sum(
            row["generation_status"] == "missing" for row in results
        ),
        "sympy_accuracy": sympy_accuracy,
        "sympy_accuracy_completed_generations": sympy_accuracy_completed,
        "sympy_fully_accepted_count": sum(row["sympy_accepted"] for row in results),
        "llm_judge_eligible_problem_count": sum(
            row["judge_status"] == "not_run" for row in results
        ),
        "llm_judged_problem_count": 0,
        "llm_judge_call_error_count": 0,
        "combined_accuracy": None,
        "combined_accuracy_completed_generations": None,
        "scoring": (
            "Mean per-problem fraction of extracted boxed answers matching any "
            "reference answer, preserving the supplied PHYSICS evaluator metric."
        ),
        "judge_model": None,
    }
    summary_path = args.output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
