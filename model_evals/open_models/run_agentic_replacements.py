#!/usr/bin/env python3
"""Replace incorrect open-model attempts with Codex-harness retries."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval.backends import make_judge, validate_judgment
from eval.storage import atomic_json, fingerprint
from model_evals.open_models.run_agentic_hle_smoke import SYSTEM_PROMPT
from utils.codex_cli import CodexLLM, validate_codex_result


DEFAULT_SOURCE = (
    ROOT
    / "model_evals/kimi/runs/kimi-k3-max-no-tools-20260917/hle-corrected"
)
DEFAULT_DATASETS = ("hle", "critpt", "cmt")
ATTEMPTS = (1, 2, 3, 4)


def read_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def append_error(path: Path, task: dict, stage: str, exc: BaseException) -> None:
    record = {
        "dataset": task["dataset"],
        "attempt": task["attempt"],
        "id": task["id"],
        "stage": stage,
        "error": f"{type(exc).__name__}: {exc}",
        "time": datetime.now(timezone.utc).isoformat(),
    }
    with path.open("a") as handle:
        handle.write(json.dumps(record) + "\n")


def checkpoint_path(output: Path, task: dict, filename: str) -> Path:
    return output / task["dataset"] / f'attempt-{task["attempt"]}' / filename


def load_sources(source: Path, datasets: tuple[str, ...]) -> tuple[list[dict], dict]:
    tasks = []
    originals = {}
    for dataset in datasets:
        canonical_ids = None
        for attempt in ATTEMPTS:
            directory = source / dataset / f"attempt-{attempt}"
            rows = read_json(directory / "dataset.json")
            predictions = read_json(directory / "predictions.json")
            judgments = read_json(directory / "judgments.json")
            if not isinstance(rows, list) or not isinstance(predictions, dict) or not isinstance(judgments, dict):
                raise ValueError(f"Incomplete source artifacts: {directory}")
            ids = [row["id"] for row in rows]
            if canonical_ids is None:
                canonical_ids = ids
            elif ids != canonical_ids:
                raise ValueError(f"Question order changed across {dataset} attempts")
            if set(predictions) != set(ids) or set(judgments) != set(ids):
                raise ValueError(f"Source attempt is incomplete: {directory}")
            originals[(dataset, attempt)] = {
                "rows": rows,
                "predictions": predictions,
                "judgments": judgments,
            }
            for row in rows:
                qid = row["id"]
                judgment = judgments[qid].get("judgment", {})
                validate_judgment(judgment)
                if judgment["correct"] == "no":
                    tasks.append(
                        {
                            "dataset": dataset,
                            "attempt": attempt,
                            "id": qid,
                            "row": row,
                            "original_prediction_sha256": fingerprint(predictions[qid]),
                            "original_judgment_sha256": fingerprint(judgments[qid]),
                        }
                    )
    return tasks, originals


def agent_client(args) -> CodexLLM:
    requested_model = f"{args.model}@preset/{args.preset}"
    return CodexLLM(
        model=requested_model,
        model_reasoning_effort=args.reasoning_effort,
        timeout=args.timeout,
        system_prompt=SYSTEM_PROMPT,
        strict_no_tools=False,
        max_exec_retries=2,
        web_search="disabled",
        sandbox_mode="workspace-write",
        env_inherit="none",
        reasoning_summary="concise",
        capture_workspace=False,
        config_overrides=[
            'model_provider="openrouter"',
            'model_providers.openrouter.name="OpenRouter"',
            'model_providers.openrouter.base_url="https://openrouter.ai/api/v1"',
            'model_providers.openrouter.env_key="OPENROUTER_API_KEY"',
            'model_providers.openrouter.wire_api="responses"',
            "model_providers.openrouter.supports_websockets=false",
            "model_context_window=1048576",
            "model_auto_compact_token_limit=900000",
        ],
    )


def generate_one(client: CodexLLM, task: dict, requested_model: str) -> dict:
    result = client.complete(task["row"]["question"])
    validate_codex_result(result)
    tool_events = []
    for event in result.events:
        item = event.get("item") or {}
        if item.get("type") in {
            "command_execution",
            "file_change",
            "mcp_tool_call",
            "web_search",
        }:
            tool_events.append(item)
    return {
        "response": result.text,
        "usage": result.usage,
        "requested_model": requested_model,
        "actual_model": None,
        "attempts": result.attempts,
        "tool_events": tool_events,
        "refused": False,
        "replaces": {
            "dataset": task["dataset"],
            "attempt": task["attempt"],
            "id": task["id"],
            "original_prediction_sha256": task["original_prediction_sha256"],
            "original_judgment_sha256": task["original_judgment_sha256"],
        },
    }


def judge_args(args):
    return SimpleNamespace(
        judge_model="gpt-5.6-sol",
        judge_reasoning_effort="high",
        judge_max_output_tokens=32768,
        model="kimi-k3",
        reasoning_effort=args.reasoning_effort,
        codex_bin=args.codex_bin,
        timeout=args.timeout,
        fable_model=None,
    )


def load_checkpoints(output: Path, tasks: list[dict], filename: str) -> dict:
    checkpoints = {}
    for task in tasks:
        key = (task["dataset"], task["attempt"])
        if key not in checkpoints:
            path = checkpoint_path(output, task, filename)
            value = read_json(path, {})
            if not isinstance(value, dict):
                raise ValueError(f"Invalid checkpoint: {path}")
            checkpoints[key] = value
    return checkpoints


def save_checkpoint(output: Path, task: dict, filename: str, checkpoints: dict) -> None:
    key = (task["dataset"], task["attempt"])
    path = checkpoint_path(output, task, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    # The packaged Codex binary performs aggressive stale-temp cleanup while
    # many processes start concurrently.  Avoid tempfile's ``tmp*`` prefix so
    # checkpoint files cannot be mistaken for disposable runtime directories.
    partial = path.with_name(f".{path.name}.{os.getpid()}.partial")
    payload = json.dumps(checkpoints[key], indent=2, ensure_ascii=False) + "\n"
    last_error = None
    for attempt in range(5):
        try:
            with partial.open("w") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            partial.replace(path)
            return
        except FileNotFoundError as exc:
            last_error = exc
            time.sleep(0.1 * (attempt + 1))
    raise last_error


def parse_dataset_map(values: list[str]) -> dict[str, str]:
    mapping = {}
    for value in values:
        target, separator, seed = value.partition("=")
        if not separator or not target or not seed:
            raise ValueError(f"Invalid dataset mapping {value!r}; expected TARGET=SEED")
        if target in mapping and mapping[target] != seed:
            raise ValueError(f"Conflicting seed mapping for {target}")
        mapping[target] = seed
    return mapping


def seed_replacements(
    output: Path,
    tasks: list[dict],
    predictions: dict,
    judgments: dict,
    seed_output: Path | None,
    dataset_map: dict[str, str],
) -> int:
    if seed_output is None:
        return 0
    if not seed_output.is_dir():
        raise ValueError(f"Seed output does not exist: {seed_output}")
    cache = {}
    changed = set()
    seeded = 0
    for task in tasks:
        key = (task["dataset"], task["attempt"])
        if task["id"] in predictions[key] and task["id"] in judgments[key]:
            continue
        seed_dataset = dataset_map.get(task["dataset"], task["dataset"])
        seed_key = (seed_dataset, task["attempt"])
        if seed_key not in cache:
            directory = seed_output / seed_dataset / f"attempt-{task['attempt']}"
            cache[seed_key] = (
                read_json(directory / "predictions.json", {}),
                read_json(directory / "judgments.json", {}),
            )
        seed_predictions, seed_judgments = cache[seed_key]
        prediction = seed_predictions.get(task["id"])
        judgment = seed_judgments.get(task["id"])
        if not isinstance(prediction, dict) or not isinstance(judgment, dict):
            continue
        replaces = prediction.get("replaces", {})
        if (
            replaces.get("original_prediction_sha256")
            != task["original_prediction_sha256"]
            or replaces.get("original_judgment_sha256")
            != task["original_judgment_sha256"]
        ):
            continue
        validate_judgment(judgment.get("judgment"))
        if judgment.get("prediction_sha256") != fingerprint(prediction):
            raise ValueError(
                f"Stale seeded judgment: {seed_dataset}/attempt-{task['attempt']}/{task['id']}"
            )
        predictions[key][task["id"]] = prediction
        judgments[key][task["id"]] = judgment
        changed.add(key)
        seeded += 1
    representative = {
        (task["dataset"], task["attempt"]): task for task in tasks
    }
    for key in changed:
        task = representative[key]
        save_checkpoint(output, task, "predictions.json", predictions)
        save_checkpoint(output, task, "judgments.json", judgments)
    return seeded


def combined_summary(
    originals: dict, replacement_judgments: dict, datasets: tuple[str, ...]
) -> dict:
    dataset_results = {}
    total_retries = 0
    total_retry_successes = 0
    for dataset in datasets:
        per_attempt = []
        grades_by_id = {}
        original_grades_by_id = {}
        dataset_retries = 0
        dataset_successes = 0
        complete = True
        for attempt in ATTEMPTS:
            original = originals[(dataset, attempt)]
            replacements = replacement_judgments[(dataset, attempt)]
            final_correct = 0
            original_correct = 0
            retry_count = 0
            retry_successes = 0
            for row in original["rows"]:
                qid = row["id"]
                was_correct = original["judgments"][qid]["judgment"]["correct"] == "yes"
                original_grades_by_id.setdefault(qid, []).append(was_correct)
                if was_correct:
                    is_correct = True
                    original_correct += 1
                else:
                    retry_count += 1
                    replacement = replacements.get(qid)
                    if replacement is None:
                        complete = False
                        is_correct = False
                    else:
                        validate_judgment(replacement.get("judgment"))
                        is_correct = replacement["judgment"]["correct"] == "yes"
                        retry_successes += int(is_correct)
                grades_by_id.setdefault(qid, []).append(is_correct)
                final_correct += int(is_correct)
            count = len(original["rows"])
            per_attempt.append(
                {
                    "attempt": attempt,
                    "questions": count,
                    "original_correct": original_correct,
                    "retries": retry_count,
                    "retry_successes": retry_successes,
                    "final_correct": final_correct if complete else None,
                    "final_accuracy": final_correct / count if complete else None,
                }
            )
            dataset_retries += retry_count
            dataset_successes += retry_successes
        question_count = len(grades_by_id)
        original_correct_total = sum(sum(values) for values in original_grades_by_id.values())
        final_correct_total = sum(sum(values) for values in grades_by_id.values())
        original_passes = sum(any(values) for values in original_grades_by_id.values())
        final_passes = sum(any(values) for values in grades_by_id.values())
        dataset_results[dataset] = {
            "complete": complete,
            "questions": question_count,
            "attempts": 4,
            "retries": dataset_retries,
            "retry_successes": dataset_successes,
            "retry_success_rate": dataset_successes / dataset_retries,
            "original_mean_at_4": original_correct_total / (4 * question_count),
            "final_mean_at_4": final_correct_total / (4 * question_count) if complete else None,
            "original_pass_at_4": original_passes / question_count,
            "final_pass_at_4": final_passes / question_count if complete else None,
            "per_attempt": per_attempt,
        }
        total_retries += dataset_retries
        total_retry_successes += dataset_successes
    return {
        "complete": all(value["complete"] for value in dataset_results.values()),
        "model": "moonshotai/kimi-k3",
        "reasoning_effort": "max",
        "replacement_harness": "Codex CLI with local tools and OpenRouter agentic-web preset",
        "judge_model": "gpt-5.6-sol",
        "total_retries": total_retries,
        "total_retry_successes": total_retry_successes,
        "retry_success_rate": total_retry_successes / total_retries if total_retries else None,
        "datasets": dataset_results,
    }


def write_report(output: Path, summary: dict, datasets: tuple[str, ...]) -> None:
    lines = [
        "# Kimi K3 Max: agentic replacement results",
        "",
        "Every incorrect attempt in the selected saved evaluation runs was",
        "replaced by an independent Kimi K3 Max retry using the Codex harness, local",
        "tools, and the OpenRouter `agentic-web` preset. Existing correct attempts were",
        "preserved. Replacement answers were judged by GPT-5.6-Sol High.",
        "",
        "| Dataset | Retries | Retry correct | Original mean@4 | Final mean@4 | Original pass@4 | Final pass@4 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for dataset in datasets:
        row = summary["datasets"][dataset]
        percent = lambda value: "pending" if value is None else f"{100 * value:.2f}%"
        lines.append(
            f"| {dataset} | {row['retries']} | {row['retry_successes']} | "
            f"{percent(row['original_mean_at_4'])} | {percent(row['final_mean_at_4'])} | "
            f"{percent(row['original_pass_at_4'])} | {percent(row['final_pass_at_4'])} |"
        )
    lines.extend(
        [
            "",
            f"Overall replacement success: {summary['total_retry_successes']}/{summary['total_retries']} "
            f"({100 * summary['retry_success_rate']:.2f}%).",
            "",
        ]
    )
    (output / "RESULTS.md").write_text("\n".join(lines))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--datasets",
        nargs="+",
        default=list(DEFAULT_DATASETS),
        help="Source dataset directory names to process",
    )
    p.add_argument(
        "--seed-output",
        type=Path,
        help="Reuse matching completed replacement predictions and judgments",
    )
    p.add_argument(
        "--seed-dataset-map",
        nargs="*",
        default=[],
        metavar="TARGET=SEED",
        help="Map source dataset directories to names used by --seed-output",
    )
    p.add_argument("--model", default="moonshotai/kimi-k3")
    p.add_argument("--preset", default="agentic-web")
    p.add_argument("--reasoning-effort", default="max")
    p.add_argument("--generation-workers", type=int, default=48)
    p.add_argument("--judge-workers", type=int, default=16)
    p.add_argument("--timeout", type=float, default=3600)
    p.add_argument("--codex-bin", default="codex")
    p.add_argument("--stage", choices=("generate", "judge", "summary", "all"), default="all")
    return p


def main() -> int:
    args = parser().parse_args()
    if not os.environ.get("OPENROUTER_API_KEY") and args.stage in {"generate", "all"}:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    if min(args.generation_workers, args.judge_workers, args.timeout) <= 0:
        raise ValueError("worker counts and timeout must be positive")
    datasets = tuple(dict.fromkeys(args.datasets))
    if not datasets or any(not dataset.strip() for dataset in datasets):
        raise ValueError("at least one non-empty dataset is required")
    tasks, originals = load_sources(args.source, datasets)
    seed_dataset_map = parse_dataset_map(args.seed_dataset_map)
    requested_model = f"{args.model}@preset/{args.preset}"
    counts = {
        dataset: sum(task["dataset"] == dataset for task in tasks) for dataset in datasets
    }
    manifest = {
        "version": 1,
        "source": str(args.source.resolve()),
        "datasets": counts,
        "total_retries": len(tasks),
        "model": args.model,
        "requested_model": requested_model,
        "reasoning_effort": args.reasoning_effort,
        "harness": "codex exec",
        "tools": ["codex local tools", "openrouter:web_search"],
        "openrouter_preset": args.preset,
        "sandbox": "workspace-write",
        "judge_model": "gpt-5.6-sol",
        "judge_reasoning_effort": "high",
        "replacement_policy": "replace every original incorrect attempt; preserve original correct attempts",
        "seed_output": str(args.seed_output.resolve()) if args.seed_output else None,
        "seed_dataset_map": seed_dataset_map,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    existing = read_json(args.output / "manifest.json")
    if existing is not None and existing != manifest:
        raise ValueError("Output manifest differs; choose a new output directory")
    atomic_json(args.output / "manifest.json", manifest)
    atomic_json(
        args.output / "plan.json",
        {
            "total": len(tasks),
            "by_dataset": counts,
            "generation_workers": args.generation_workers,
            "judge_workers": args.judge_workers,
        },
    )

    predictions = load_checkpoints(args.output, tasks, "predictions.json")
    judgments = load_checkpoints(args.output, tasks, "judgments.json")
    seeded = seed_replacements(
        args.output,
        tasks,
        predictions,
        judgments,
        args.seed_output,
        seed_dataset_map,
    )
    if args.seed_output:
        print(f"seeded {seeded} matching completed replacements", flush=True)
    atomic_json(
        args.output / "plan.json",
        {
            "total": len(tasks),
            "by_dataset": counts,
            "seeded": sum(len(value) for value in predictions.values()),
            "pending_generation": len(tasks) - sum(len(value) for value in predictions.values()),
            "generation_workers": args.generation_workers,
            "judge_workers": args.judge_workers,
        },
    )
    if args.stage in {"generate", "all"}:
        pending = [
            task
            for task in tasks
            if task["id"] not in predictions[(task["dataset"], task["attempt"])]
        ]
        client = agent_client(args)
        completed = len(tasks) - len(pending)
        with ThreadPoolExecutor(max_workers=min(args.generation_workers, len(pending) or 1)) as pool:
            futures = {
                pool.submit(generate_one, client, task, requested_model): task for task in pending
            }
            for future in as_completed(futures):
                task = futures[future]
                key = (task["dataset"], task["attempt"])
                try:
                    predictions[key][task["id"]] = future.result()
                    save_checkpoint(args.output, task, "predictions.json", predictions)
                    completed += 1
                    print(
                        f"generated {completed}/{len(tasks)} "
                        f"{task['dataset']}/attempt-{task['attempt']}/{task['id']}",
                        flush=True,
                    )
                except Exception as exc:
                    append_error(args.output / "errors.jsonl", task, "generate", exc)
                    print(
                        f"generation failed {task['dataset']}/attempt-{task['attempt']}/"
                        f"{task['id']}: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )

    if args.stage in {"judge", "all"}:
        pending = [
            task
            for task in tasks
            if task["id"] in predictions[(task["dataset"], task["attempt"])]
            and task["id"] not in judgments[(task["dataset"], task["attempt"])]
        ]
        judge = make_judge(judge_args(args))
        completed = sum(len(value) for value in judgments.values())

        def judge_one(task: dict) -> dict:
            key = (task["dataset"], task["attempt"])
            prediction = predictions[key][task["id"]]
            result = judge(task["row"], prediction)
            validate_judgment(result["judgment"])
            return {**result, "prediction_sha256": fingerprint(prediction)}

        with ThreadPoolExecutor(max_workers=min(args.judge_workers, len(pending) or 1)) as pool:
            futures = {pool.submit(judge_one, task): task for task in pending}
            for future in as_completed(futures):
                task = futures[future]
                key = (task["dataset"], task["attempt"])
                try:
                    judgments[key][task["id"]] = future.result()
                    save_checkpoint(args.output, task, "judgments.json", judgments)
                    completed += 1
                    verdict = judgments[key][task["id"]]["judgment"]["correct"]
                    print(
                        f"judged {completed}/{len(tasks)} {verdict} "
                        f"{task['dataset']}/attempt-{task['attempt']}/{task['id']}",
                        flush=True,
                    )
                except Exception as exc:
                    append_error(args.output / "errors.jsonl", task, "judge", exc)
                    print(
                        f"judgment failed {task['dataset']}/attempt-{task['attempt']}/"
                        f"{task['id']}: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )

    summary = combined_summary(originals, judgments, datasets)
    atomic_json(args.output / "summary.json", summary)
    write_report(args.output, summary, datasets)
    print(json.dumps(summary, indent=2), flush=True)
    if args.stage == "generate":
        return 0 if sum(len(value) for value in predictions.values()) == len(tasks) else 2
    return 0 if summary["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
