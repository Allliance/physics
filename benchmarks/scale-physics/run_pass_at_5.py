"""Run adaptive ScalePhysics attempts 2--5, stopping after each first success."""

from __future__ import annotations

import argparse
import json
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import evaluate


def attempt_paths(run_dir: Path, attempt: int) -> tuple[Path, Path, Path]:
    suffix = "" if attempt == 1 else f"_attempt_{attempt}"
    return (
        run_dir / f"responses{suffix}.jsonl",
        run_dir / f"judgments{suffix}.jsonl",
        run_dir / f"failures{suffix}.jsonl",
    )


def solved_keys(judgments_by_attempt: dict[int, dict[str, dict[str, Any]]]) -> set[str]:
    return {
        key
        for judgments in judgments_by_attempt.values()
        for key, judgment in judgments.items()
        if judgment.get("correct") is True
    }


def run_attempt(
    rows: list[dict[str, Any]],
    run_dir: Path,
    config: evaluate.Config,
    attempt: int,
    *,
    generate_missing: bool,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    responses_path, judgments_path, failures_path = attempt_paths(run_dir, attempt)
    responses = evaluate.load_jsonl(responses_path)
    judgments = evaluate.load_jsonl(judgments_path)
    binary = evaluate.codex_binary()
    lock = threading.Lock()

    def client(model: str, effort: str) -> evaluate.CodexLLM:
        return evaluate.CodexLLM(
            model=model,
            model_reasoning_effort=effort,
            codex_bin=binary,
            timeout=config.timeout,
        )

    def process(row: dict[str, Any]) -> None:
        key = evaluate.row_key(row)
        try:
            if key not in responses:
                if not generate_missing:
                    return
                result = client(config.model, config.reasoning_effort).complete(
                    f"Problem:\n{row['question']}", system_prompt=evaluate.GENERATOR_SYSTEM
                )
                response = {
                    "key": key,
                    "id": row["id"],
                    "attempt": attempt,
                    "response": result.text,
                    "usage": result.usage,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                with lock:
                    evaluate.append_jsonl(responses_path, response)
                    responses[key] = response
            if key in judgments:
                return
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as schema:
                json.dump(evaluate.JUDGE_SCHEMA, schema)
                schema.flush()
                result = client(config.judge_model, config.judge_reasoning_effort).complete(
                    evaluate.judge_prompt(row, responses[key]["response"]),
                    system_prompt=evaluate.JUDGE_SYSTEM,
                    output_schema=Path(schema.name),
                )
            parsed = evaluate.parse_json_object(result.text)
            judgment = {
                "key": key,
                "id": row["id"],
                "attempt": attempt,
                "correct": parsed.get("correct") is True,
                "reason": str(parsed.get("reason", "")),
                "judge_response": result.text,
                "usage": result.usage,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            with lock:
                evaluate.append_jsonl(judgments_path, judgment)
                judgments[key] = judgment
        except Exception as exc:
            failure = {
                "key": key,
                "id": row.get("id"),
                "attempt": attempt,
                "error": f"{type(exc).__name__}: {exc}",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            with lock:
                evaluate.append_jsonl(failures_path, failure)

    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        list(executor.map(process, rows))
    return responses, judgments


def build_summary(
    rows: list[dict[str, Any]],
    responses_by_attempt: dict[int, dict[str, dict[str, Any]]],
    judgments_by_attempt: dict[int, dict[str, dict[str, Any]]],
    config: evaluate.Config,
) -> dict[str, Any]:
    sample_keys = {evaluate.row_key(row) for row in rows}
    solved: set[str] = set()
    cumulative: dict[str, float] = {}
    attempt_counts: dict[str, dict[str, int]] = {}
    first_success: dict[str, int] = {}
    for attempt in range(1, 6):
        responses = responses_by_attempt.get(attempt, {})
        judgments = judgments_by_attempt.get(attempt, {})
        attempted = sample_keys.intersection(responses)
        judged = sample_keys.intersection(judgments)
        newly_solved = {
            key for key in judged if judgments[key].get("correct") is True and key not in solved
        }
        for key in newly_solved:
            first_success[key] = attempt
        solved.update(newly_solved)
        cumulative[f"pass@{attempt}"] = len(solved) / len(rows)
        attempt_counts[str(attempt)] = {
            "num_attempted": len(attempted),
            "num_judged": len(judged),
            "num_newly_solved": len(newly_solved),
        }
    return {
        "sample_size": len(rows),
        "seed": config.seed,
        "model": config.model,
        "reasoning_effort": config.reasoning_effort,
        "judge_model": config.judge_model,
        "judge_reasoning_effort": config.judge_reasoning_effort,
        "stopping_policy": "stop after first correct judgment",
        "attempts": attempt_counts,
        "cumulative": cumulative,
        "num_solved_by_5": len(solved),
        "num_unsolved_after_5": len(rows) - len(solved),
        "first_success_attempt": first_success,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def run(config: evaluate.Config, output_root: Path) -> Path:
    all_rows = evaluate.read_rows(evaluate.DEFAULT_DATASET)
    rows = evaluate.select_rows(all_rows, config.sample_size, config.seed)
    run_dir = output_root / config.run_name
    if not (run_dir / "sample.jsonl").is_file():
        raise RuntimeError(f"attempt-1 artifacts are missing from {run_dir}")

    responses_by_attempt = {1: evaluate.load_jsonl(attempt_paths(run_dir, 1)[0])}
    judgments_by_attempt = {1: evaluate.load_jsonl(attempt_paths(run_dir, 1)[1])}

    for attempt in range(2, 6):
        prior_solved = solved_keys(judgments_by_attempt)
        eligible = [row for row in rows if evaluate.row_key(row) not in prior_solved]
        responses, judgments = run_attempt(
            eligible, run_dir, config, attempt, generate_missing=True
        )
        responses_by_attempt[attempt] = responses
        judgments_by_attempt[attempt] = judgments

    summary = build_summary(rows, responses_by_attempt, judgments_by_attempt, config)
    (run_dir / "pass_at_5_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=evaluate.DEFAULT_OUTPUT)
    parser.add_argument("--max-workers", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args()
    config = evaluate.Config(max_workers=args.max_workers, timeout=args.timeout)
    print(run(config, args.output_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
