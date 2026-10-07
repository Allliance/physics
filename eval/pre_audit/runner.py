"""Resumable generation and original-evaluator scoring for pre-audit data."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import shutil
import sys

from utils.fable_backend import resolve_fable_model

from eval.backends import make_predictor
from eval.storage import atomic_json, file_hash, fingerprint, require_checkpoint
from .pipeline import DATASETS, JudgeSettings, load_benchmark


MODELS = [
    "claude-fable-5", "gpt-5.6-sol", "gpt-5.6-luna", "gpt-6-astra",
    "gemini-3.1-pro-preview", "gpt-oss-120b", "kimi-k3", "glm-5.3",
    "deepseek-v4-pro", "qwen3.8-27b",
]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dataset", required=True,
                        help="One benchmark name, or 'all' for all six")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=1,
                        help="Independent attempts per question (use 4 for mean@4/pass@4)")
    parser.add_argument("--model", choices=MODELS, default="claude-fable-5")
    parser.add_argument("--reasoning-effort",
                        choices=["low", "medium", "high", "xhigh", "max"],
                        default="high")
    parser.add_argument("--judge-model", choices=["gpt-5.6-sol", "gpt-6-astra", "claude-fable-5"],
                        default="gpt-5.6-sol")
    parser.add_argument("--judge-reasoning-effort", choices=["low", "medium", "high", "xhigh"],
                        default="high")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--score-workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--grade-timeout", type=float, default=180.0)
    parser.add_argument("--max-output-tokens", type=int, default=32768)
    parser.add_argument("--judge-max-output-tokens", type=int, default=8192)
    parser.add_argument("--max-pending", type=int,
                        help="Cap pending rows per stage and attempt for smoke tests")
    parser.add_argument("--stage", choices=["prepare", "generate", "score", "summary", "all"],
                        default="all")
    parser.add_argument("--fable-model")
    parser.add_argument("--codex-bin", default=shutil.which("codex") or
                        str(Path.home() / ".local/bin/codex"))
    parser.add_argument("--no-ugphysics-auxiliary", action="store_true")
    parser.add_argument("--dry-run", action="store_true")


def _checkpoint(path: Path, ids: list[str]) -> dict[str, dict]:
    value = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(value, dict) or set(value) - set(ids):
        raise ValueError(f"Checkpoint contains unexpected IDs: {path}")
    return value


def _work(args, rows, checkpoint, filename, action) -> None:
    pending = [row for row in rows if row.id not in checkpoint]
    if args.max_pending is not None:
        pending = pending[:args.max_pending]
    if not pending:
        return
    workers = args.workers if filename == "predictions.json" else args.score_workers
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(action, row): row.id for row in pending}
        for future in as_completed(futures):
            qid = futures[future]
            try:
                checkpoint[qid] = future.result()
                atomic_json(args._attempt_output / filename, checkpoint)
                print(f"{args._dataset} attempt {args._attempt} {filename}: "
                      f"{len(checkpoint)}/{len(rows)} ({qid})", flush=True)
            except Exception as error:
                record = {
                    "id": qid, "stage": filename,
                    "error": f"{type(error).__name__}: {error}",
                    "time": datetime.now(timezone.utc).isoformat(),
                }
                with (args._attempt_output / "errors.jsonl").open("a") as handle:
                    handle.write(json.dumps(record) + "\n")
                print(f"{filename}: failed {qid}: {record['error']}",
                      file=sys.stderr, flush=True)


def _summary(problems, predictions, scores, pipeline) -> dict:
    rows = []
    for problem in problems:
        result = scores.get(problem.id)
        rows.append({"id": problem.id,
                     "correct": None if result is None else bool(result["correct"])})
    complete = len(predictions) == len(problems) and all(row["correct"] is not None for row in rows)
    correct = sum(row["correct"] is True for row in rows)
    return {
        "protocol": "pre-audit", "dataset": pipeline.dataset,
        "evaluator": pipeline.metadata["evaluator"], "questions": len(problems),
        "generated": len(predictions), "scored": len(scores), "correct": correct,
        "complete": complete, "accuracy": correct / len(problems) if complete else None,
        "per_question": rows,
    }


def _run_attempt(args, dataset: str, attempt: int) -> int:
    output = args.output / dataset / f"attempt-{attempt}"
    args._attempt_output, args._dataset, args._attempt = output, dataset, attempt
    settings = JudgeSettings(
        model=args.judge_model, reasoning_effort=args.judge_reasoning_effort,
        timeout=args.timeout, max_output_tokens=args.judge_max_output_tokens,
        fable_model=args.fable_model, codex_bin=args.codex_bin,
    )
    pipeline = load_benchmark(
        dataset, judge_settings=settings,
        use_ugphysics_auxiliary=not args.no_ugphysics_auxiliary,
    )
    problems = list(pipeline.problems)
    api_model = resolve_fable_model(args.fable_model) if args.model == "claude-fable-5" else None
    manifest = {
        "version": 1, "protocol": "pre-audit", "dataset": dataset, "attempt": attempt,
        "source": pipeline.metadata["source"],
        "source_sha256": pipeline.metadata["source_sha256"],
        "questions": len(problems), "ids": [problem.id for problem in problems],
        "model": args.model, "reasoning_effort": args.reasoning_effort,
        "max_output_tokens": args.max_output_tokens, "tools": False,
        "judge_model": args.judge_model,
        "judge_reasoning_effort": args.judge_reasoning_effort,
        "evaluator": pipeline.metadata["evaluator"],
        "grade_timeout": args.grade_timeout,
        "implementation_sha256": {
            str(path.relative_to(Path(__file__).parents[1])): file_hash(path)
            for path in (
                Path(__file__), Path(__file__).with_name("pipeline.py"),
                Path(__file__).with_name("native.py"), Path(__file__).parents[1] / "backends.py",
            )
        },
    }
    if dataset == "hle-physics":
        from .hle import provenance

        manifest["evaluator_source"] = provenance()
    elif dataset in {"phybench", "prism", "ugphysics"}:
        from .native import provenance

        manifest["evaluator_source"] = provenance(dataset)
    elif dataset == "critpt":
        from .critpt import provenance

        manifest["evaluator_source"] = provenance()
    manifest["shared_backend_sha256"] = file_hash(
        Path(__file__).parents[2] / "utils/fable_backend.py")
    if args.model in {"gpt-oss-120b", "kimi-k3", "glm-5.3", "deepseek-v4-pro",
                      "qwen3.8-27b"}:
        from utils.openai_compatible import backend_metadata

        generation = backend_metadata()
        generation["route_sha256"] = fingerprint(generation["base_url"])
        manifest["generation"] = generation
    if args.dry_run:
        print(json.dumps(manifest, indent=2))
        return 0
    output.mkdir(parents=True, exist_ok=True)
    lock = (output / ".lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise ValueError(f"Another process is using {output}") from None
    try:
        require_checkpoint(output / "manifest.json", manifest)
        require_checkpoint(output / "dataset.json", [problem.as_dict() for problem in problems])
        ids = [problem.id for problem in problems]
        predictions = _checkpoint(output / "predictions.json", ids)
        scores = _checkpoint(output / "scores.json", ids)
        for qid, prediction in predictions.items():
            if (not prediction.get("refused") and
                    (not isinstance(prediction.get("response"), str) or
                     not prediction["response"].strip())):
                raise ValueError(f"Invalid prediction checkpoint: {qid}")
        for qid, score in scores.items():
            if qid not in predictions or score.get("prediction_sha256") != fingerprint(predictions[qid]):
                raise ValueError(f"Prediction changed after scoring: {qid}")
        if args.stage in {"all", "generate"}:
            predict = make_predictor(args, api_model)
            _work(args, problems, predictions, "predictions.json",
                  lambda problem: predict(problem.predictor_input()))
        if args.stage in {"all", "score"}:
            def score(problem):
                prediction = predictions[problem.id]
                if prediction.get("refused"):
                    return {"dataset": dataset, "id": problem.id, "correct": False,
                            "score": 0.0, "evaluator": "model refusal", "details": {},
                            "prediction_sha256": fingerprint(prediction)}
                result = pipeline.evaluate(problem.id, prediction["response"],
                                           timeout=args.grade_timeout).as_dict()
                return {**result, "prediction_sha256": fingerprint(prediction)}

            scoreable = [problem for problem in problems if problem.id in predictions]
            _work(args, scoreable, scores, "scores.json", score)
        summary = _summary(problems, predictions, scores, pipeline)
        atomic_json(output / "summary.json", summary)
        return 0 if summary["complete"] or args.stage in {"prepare", "generate"} else 2
    finally:
        lock.close()


def _aggregate(args, datasets: list[str]) -> dict:
    result = {"protocol": "pre-audit", "attempts": args.attempts,
              "model": args.model, "benchmarks": {}}
    for dataset in datasets:
        pipeline = load_benchmark(dataset)
        ids = [problem.id for problem in pipeline.problems]
        by_id = {qid: [] for qid in ids}
        completed = True
        for attempt in range(1, args.attempts + 1):
            path = args.output / dataset / f"attempt-{attempt}" / "scores.json"
            scores = json.loads(path.read_text()) if path.exists() else {}
            completed &= len(scores) == len(ids)
            for qid in ids:
                if qid in scores:
                    by_id[qid].append(bool(scores[qid]["correct"]))
        total = sum(len(values) for values in by_id.values())
        correct = sum(sum(values) for values in by_id.values())
        result["benchmarks"][dataset] = {
            "questions": len(ids), "completed_scores": total,
            "complete": completed,
            f"mean@{args.attempts}": correct / (len(ids) * args.attempts) if completed else None,
            f"pass@{args.attempts}": sum(any(values) for values in by_id.values()) / len(ids)
            if completed else None,
        }
    atomic_json(args.output / "summary.json", result)
    return result


def run(args) -> int:
    if min(args.attempts, args.workers, args.score_workers, args.timeout,
           args.grade_timeout, args.max_output_tokens, args.judge_max_output_tokens) <= 0:
        raise ValueError("Attempts, workers, timeouts, and token limits must be positive")
    if args.max_pending is not None and args.max_pending <= 0:
        raise ValueError("--max-pending must be positive")
    if args.model == args.judge_model:
        raise ValueError("Choose a judge different from the evaluated model")
    datasets = (list(DATASETS) if args.dataset.casefold() == "all" else
                [load_benchmark(args.dataset).dataset])
    status = 0
    for dataset in datasets:
        for attempt in range(1, args.attempts + 1):
            status = max(status, _run_attempt(args, dataset, attempt))
    if not args.dry_run:
        aggregate = _aggregate(args, datasets)
        print(json.dumps(aggregate, indent=2))
    return status
