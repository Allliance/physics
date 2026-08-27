"""Judge SymPy-rejected PHYSICS answers with Codex and retain every call."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BENCHMARK_ROOT = Path(__file__).parent
REPO_ROOT = BENCHMARK_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.codex_cli import CodexLLM  # noqa: E402


JUDGE_SYSTEM_PROMPT = (
    "You are an assistant that compares LaTeX expressions for equivalence."
)
DEFAULT_EVALUATION_DIR = (
    REPO_ROOT / "audit" / "audit-data" / "PHYSICS" / "gpt-5.6-sol-high"
)


@dataclass(frozen=True)
class CandidateState:
    problem_id: str
    candidate_index: int
    candidate: str
    references: tuple[str, ...]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    temp_path.replace(path)


def artifact_metadata(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    line_count = 0
    with path.open("rb") as handle:
        for line in handle:
            digest.update(line)
            line_count += 1
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "sha256": digest.hexdigest(),
        "bytes": path.stat().st_size,
        "line_count": line_count,
    }


def build_prompt(expr1: str, expr2: str) -> str:
    """Preserve the user prompt from the benchmark's supplied LLM judge."""
    return (
        "Compare the following LaTeX expressions and check if the numerical "
        "part are same meaning content:\n\n"
        f"Expression 1:\n{expr1}\n\n"
        f"Expression 2:\n{expr2}\n\n"
        " Return True if they are equivalent, otherwise return False. focus on "
        "numerical and mathematical content. If it's multiple choice answer "
        "like a b c d, focus only on the letters"
    )


def pair_key(
    problem_id: str,
    candidate_index: int,
    reference_index: int,
    model: str,
    effort: str,
) -> tuple[str, int, int, str, str]:
    return problem_id, candidate_index, reference_index, model, effort


def judgment_id(key: tuple[str, int, int, str, str], attempt: int) -> str:
    payload = json.dumps([*key, attempt], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def judge_pair(
    state: CandidateState,
    reference_index: int,
    model: str,
    effort: str,
    timeout: float,
    attempt: int,
) -> dict[str, Any]:
    reference = state.references[reference_index]
    prompt = build_prompt(state.candidate, reference)
    key = pair_key(
        state.problem_id,
        state.candidate_index,
        reference_index,
        model,
        effort,
    )
    started_at = datetime.now(timezone.utc).isoformat()
    client = CodexLLM(
        model=model,
        model_reasoning_effort=effort,
        timeout=timeout,
        system_prompt=JUDGE_SYSTEM_PROMPT,
        strict_no_tools=True,
        max_tool_retries=3,
        max_exec_retries=2,
        exec_retry_delay=10.0,
        reasoning_summary="detailed",
    )
    try:
        result = client.complete(prompt)
        raw_response = result.text
        return {
            "judgment_id": judgment_id(key, attempt),
            "problem_id": state.problem_id,
            "candidate_index": state.candidate_index,
            "reference_index": reference_index,
            "candidate_answer": state.candidate,
            "reference_answer": reference,
            "judge_model": model,
            "judge_reasoning_effort": effort,
            "judge_system_prompt": JUDGE_SYSTEM_PROMPT,
            "judge_prompt": prompt,
            "raw_response": raw_response,
            "llm_result": "true" in raw_response.lower(),
            "usage": result.usage,
            "codex_attempts": result.attempts,
            "events": result.events,
            "attempt": attempt,
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }
    except Exception as exc:
        return {
            "judgment_id": judgment_id(key, attempt),
            "problem_id": state.problem_id,
            "candidate_index": state.candidate_index,
            "reference_index": reference_index,
            "candidate_answer": state.candidate,
            "reference_answer": reference,
            "judge_model": model,
            "judge_reasoning_effort": effort,
            "judge_system_prompt": JUDGE_SYSTEM_PROMPT,
            "judge_prompt": prompt,
            "raw_response": None,
            "llm_result": None,
            "usage": None,
            "codex_attempts": None,
            "events": None,
            "attempt": attempt,
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        }


def successful_by_pair(
    records: list[dict[str, Any]], model: str, effort: str
) -> dict[tuple[str, int, int, str, str], dict[str, Any]]:
    successful: dict[tuple[str, int, int, str, str], dict[str, Any]] = {}
    for record in records:
        if record.get("error") is not None:
            continue
        key = pair_key(
            record["problem_id"],
            record["candidate_index"],
            record["reference_index"],
            record["judge_model"],
            record["judge_reasoning_effort"],
        )
        if key[-2:] == (model, effort):
            successful[key] = record
    return successful


def attempt_counts(
    records: list[dict[str, Any]],
) -> dict[tuple[str, int, int, str, str], int]:
    counts: dict[tuple[str, int, int, str, str], int] = {}
    for record in records:
        key = pair_key(
            record["problem_id"],
            record["candidate_index"],
            record["reference_index"],
            record["judge_model"],
            record["judge_reasoning_effort"],
        )
        counts[key] = max(counts.get(key, 0), int(record.get("attempt", 1)))
    return counts


def unmatched_candidate_indices(row: dict[str, Any]) -> list[int]:
    matched = {
        comparison["candidate_index"]
        for comparison in row["sympy_comparisons"]
        if comparison.get("sympy_result") is True
    }
    return [
        index
        for index in range(len(row["candidate_answers"]))
        if index not in matched
    ]


def next_reference(
    state: CandidateState,
    successful: dict[tuple[str, int, int, str, str], dict[str, Any]],
    model: str,
    effort: str,
) -> int | None:
    for reference_index in range(len(state.references)):
        record = successful.get(
            pair_key(
                state.problem_id,
                state.candidate_index,
                reference_index,
                model,
                effort,
            )
        )
        if record is None:
            return reference_index
        if record["llm_result"] is True:
            return None
    return None


def candidate_is_resolved(
    state: CandidateState,
    successful: dict[tuple[str, int, int, str, str], dict[str, Any]],
    model: str,
    effort: str,
) -> bool:
    for reference_index in range(len(state.references)):
        record = successful.get(
            pair_key(
                state.problem_id,
                state.candidate_index,
                reference_index,
                model,
                effort,
            )
        )
        if record is None:
            return False
        if record["llm_result"] is True:
            return True
    return True


def enrich_evaluation(
    rows: list[dict[str, Any]],
    records: list[dict[str, Any]],
    model: str,
    effort: str,
) -> None:
    successful = successful_by_pair(records, model, effort)
    for row in rows:
        row["judge_model"] = model
        row["judge_reasoning_effort"] = effort
        row["judgment_ids"] = []
        if row["judge_status"] in {
            "not_needed",
            "generation_unavailable",
            "no_extracted_answers",
        }:
            row["combined_score"] = row["sympy_score"]
            continue

        corrected = round(row["sympy_score"] * len(row["candidate_answers"]))
        complete = True
        for candidate_index in unmatched_candidate_indices(row):
            candidate_matched = False
            for reference_index in range(len(row["reference_answers"])):
                record = successful.get(
                    pair_key(
                        row["id"], candidate_index, reference_index, model, effort
                    )
                )
                if record is None:
                    complete = False
                    break
                row["judgment_ids"].append(record["judgment_id"])
                if record["llm_result"] is True:
                    corrected += 1
                    candidate_matched = True
                    break
            if not complete:
                break
            if candidate_matched:
                continue

        if complete:
            row["judge_status"] = "completed"
            row["combined_score"] = corrected / len(row["candidate_answers"])
        else:
            row["judge_status"] = "not_run"
            row["combined_score"] = None


def update_summary(
    summary_path: Path,
    evaluation_path: Path,
    journal_path: Path,
    rows: list[dict[str, Any]],
    records: list[dict[str, Any]],
    model: str,
    effort: str,
) -> dict[str, Any]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    eligible = [row for row in rows if row["judge_status"] in {"completed", "not_run"}]
    judged = [row for row in eligible if row["judge_status"] == "completed"]
    completed_generations = [
        row for row in rows if row["generation_status"] == "completed"
    ]
    fully_judged = len(judged) == len(eligible)
    usage_totals: dict[str, int] = {}
    for record in records:
        for key, value in (record.get("usage") or {}).items():
            if isinstance(value, int):
                usage_totals[key] = usage_totals.get(key, 0) + value
    dataset_path = REPO_ROOT / summary["dataset"]
    responses_path = REPO_ROOT / summary["responses"]
    summary.update(
        {
            "judge_model": model,
            "judge_reasoning_effort": effort,
            "llm_judge_eligible_problem_count": len(eligible),
            "llm_judged_problem_count": len(judged),
            "llm_judge_pending_problem_count": len(eligible) - len(judged),
            "judgment_record_count": len(records),
            "successful_judgment_record_count": sum(
                record.get("error") is None for record in records
            ),
            "failed_judgment_record_count": sum(
                record.get("error") is not None for record in records
            ),
            "llm_judge_call_error_count": sum(
                record.get("error") is not None for record in records
            ),
            "judge_usage": usage_totals,
            "judge_pipeline": (
                "Codex CLI with the supplied PHYSICS pairwise equivalence prompt; "
                "the verdict is True when the raw response contains 'true'."
            ),
            "judgment_journal_is_append_only": True,
            "artifacts": {
                "dataset": artifact_metadata(dataset_path),
                "responses": artifact_metadata(responses_path),
                "evaluation": artifact_metadata(evaluation_path),
                "judgment_journal": artifact_metadata(journal_path),
            },
            "judge_updated_at": datetime.now(timezone.utc).isoformat(),
            "judge_completed_at": (
                datetime.now(timezone.utc).isoformat() if fully_judged else None
            ),
            "combined_accuracy": (
                sum(row["combined_score"] for row in rows) / len(rows)
                if fully_judged
                else None
            ),
            "combined_accuracy_completed_generations": (
                sum(row["combined_score"] for row in completed_generations)
                / len(completed_generations)
                if fully_judged
                else None
            ),
            "evaluation_file": str(evaluation_path.relative_to(REPO_ROOT)),
            "judgment_journal": str(journal_path.relative_to(REPO_ROOT)),
        }
    )
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation-dir", type=Path, default=DEFAULT_EVALUATION_DIR)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument(
        "--limit-problems",
        type=int,
        help="Limit newly judged problems for a smoke test; existing records remain.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evaluation_path = args.evaluation_dir / "evaluation.jsonl"
    summary_path = args.evaluation_dir / "summary.json"
    journal_path = (
        args.evaluation_dir
        / f"judgments-{args.model}-{args.reasoning_effort}.jsonl"
    )
    rows = read_jsonl(evaluation_path)
    if not rows:
        raise SystemExit(f"No SymPy evaluation found at {evaluation_path}")

    records = read_jsonl(journal_path)
    successful = successful_by_pair(records, args.model, args.reasoning_effort)
    counts = attempt_counts(records)
    eligible_rows = [row for row in rows if row["judge_status"] == "not_run"]
    if args.limit_problems is not None:
        eligible_ids = {row["id"] for row in eligible_rows[: args.limit_problems]}
    else:
        eligible_ids = {row["id"] for row in eligible_rows}

    states: list[CandidateState] = []
    for row in eligible_rows:
        if row["id"] not in eligible_ids:
            continue
        for candidate_index in unmatched_candidate_indices(row):
            states.append(
                CandidateState(
                    problem_id=row["id"],
                    candidate_index=candidate_index,
                    candidate=row["candidate_answers"][candidate_index],
                    references=tuple(row["reference_answers"]),
                )
            )

    unresolved = [
        state
        for state in states
        if not candidate_is_resolved(
            state, successful, args.model, args.reasoning_effort
        )
    ]
    print(
        f"eligible_problems={len(eligible_rows)} selected_problems={len(eligible_ids)} "
        f"candidate_states={len(states)} unresolved={len(unresolved)} "
        f"existing_records={len(records)} workers={args.workers}",
        flush=True,
    )

    journal_path.parent.mkdir(parents=True, exist_ok=True)
    call_errors = 0
    completed_calls = 0
    with journal_path.open("a", encoding="utf-8") as journal:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            pending: dict[Future[dict[str, Any]], tuple[CandidateState, int]] = {}

            def submit(state: CandidateState) -> None:
                reference_index = next_reference(
                    state, successful, args.model, args.reasoning_effort
                )
                if reference_index is None:
                    return
                key = pair_key(
                    state.problem_id,
                    state.candidate_index,
                    reference_index,
                    args.model,
                    args.reasoning_effort,
                )
                attempt = counts.get(key, 0) + 1
                future = executor.submit(
                    judge_pair,
                    state,
                    reference_index,
                    args.model,
                    args.reasoning_effort,
                    args.timeout,
                    attempt,
                )
                pending[future] = (state, reference_index)

            for state in unresolved:
                submit(state)

            while pending:
                done, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
                for future in done:
                    state, reference_index = pending.pop(future)
                    record = future.result()
                    records.append(record)
                    journal.write(json.dumps(record, ensure_ascii=False) + "\n")
                    journal.flush()
                    os.fsync(journal.fileno())
                    completed_calls += 1
                    key = pair_key(
                        state.problem_id,
                        state.candidate_index,
                        reference_index,
                        args.model,
                        args.reasoning_effort,
                    )
                    counts[key] = record["attempt"]
                    if record["error"] is not None:
                        call_errors += 1
                    else:
                        successful[key] = record
                        if record["llm_result"] is not True:
                            submit(state)
                    if completed_calls % 10 == 0:
                        print(
                            f"new_judgments={completed_calls} active={len(pending)} "
                            f"errors={call_errors}",
                            flush=True,
                        )

    enrich_evaluation(rows, records, args.model, args.reasoning_effort)
    write_jsonl(evaluation_path, rows)
    summary = update_summary(
        summary_path,
        evaluation_path,
        journal_path,
        rows,
        records,
        args.model,
        args.reasoning_effort,
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 1 if call_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
