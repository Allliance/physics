#!/usr/bin/env python3
"""Run four fresh attempts with each benchmark's original evaluator."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PYTHON = ROOT / "model_evals/gemini/.venv/bin/python"
GEMINI = ROOT / "model_evals/gemini/runs/gemini31-20260908"
FROZEN = GEMINI / "repeated"
MODELS = {
    "kimi": ("kimi-k3", "moonshotai/Kimi-K3", "kimi-k3-max-no-tools-20260917", ROOT / "model_evals/kimi"),
    "glm": ("glm-5.3", "zai-org/GLM-5.3", "glm-5.3-max-no-tools-20260917", ROOT / "model_evals/glm"),
    "deepseek": (
        "deepseek-v4-pro", "deepseek-ai/DeepSeek-V4-Pro",
        "deepseek-v4-pro-max-no-tools-20260917", ROOT / "model_evals/deepseek",
    ),
}


def read_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def execute(name: str, argv: list[str], log: Path, complete, retries: int, env: dict) -> tuple[str, int]:
    code = 2
    for invocation in range(1, retries + 2):
        if complete():
            return name, 0
        with log.open("a") as stream:
            stream.write(f"\n[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}] invocation {invocation}\n")
            stream.write(json.dumps(argv) + "\n")
            stream.flush()
            code = subprocess.run(argv, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT).returncode
            stream.write(f"exit={code}\n")
        if complete():
            return name, 0
        if code == 1:
            break
        if invocation <= retries:
            time.sleep(30)
    return name, code or 2


def local_command(output: Path, model: str, benchmark: str, attempt: int, stage: str,
                  workers: int, score_workers: int, judge_workers: int) -> list[str]:
    return [
        str(PYTHON), "-u", "-m", "eval.suites.native_selected_mean4",
        "--output", str(output), "--model", model, "--benchmark", benchmark,
        "--attempt", str(attempt), "--stage", stage,
        "--workers", str(workers), "--score-workers", str(score_workers),
        "--judge-workers", str(judge_workers), "--grade-timeout", "180", "--timeout", "3600",
    ]


def common(model: str, workers: int) -> list[str]:
    return [
        "--model", model, "--judge-model", "gpt-5.6-sol",
        "--reasoning-effort", "max", "--judge-reasoning-effort", "high",
        "--rounds", "4", "--aggregation", "mean", "--num-workers", str(workers),
        "--round-workers", "4", "--timeout", "3600", "--max-output-tokens", "65536",
        "--no-use-tools", "--web-search", "disabled",
    ]


def native_summary_complete(path: Path) -> bool:
    return bool(read_json(path, {}).get("complete"))


def count(path: Path) -> int:
    return len(read_json(path, {}))


def run_batch(jobs: list[tuple[str, list[str], Path, object]], retries: int, env: dict) -> dict[str, int]:
    results = {}
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = [pool.submit(execute, name, argv, log, complete, retries, env)
                   for name, argv, log, complete in jobs]
        for future in as_completed(futures):
            name, code = future.result()
            results[name] = code
            print(f"{name}: exit {code}", flush=True)
    return results


def summarize(run: Path, model_key: str, model_id: str, tag: str) -> dict:
    results = {}
    native = run / "native-original" / model_key
    for benchmark in ("phybench", "prism", "ugphysics"):
        summaries = [read_json(native / benchmark / f"attempt-{attempt}/summary.json", {})
                     for attempt in range(1, 5)]
        result = {"attempts_complete": sum(bool(row.get("complete")) for row in summaries), "complete": False}
        if all(row.get("complete") for row in summaries):
            maps = [{row["id"]: bool(row["correct"]) for row in summary["per_question"]}
                    for summary in summaries]
            ids = [row["id"] for row in summaries[0]["per_question"]]
            grades = {qid: [int(values[qid]) for values in maps] for qid in ids}
            result.update(
                questions=len(ids),
                mean_at_4=sum(map(sum, grades.values())) / (4 * len(ids)),
                pass_at_4=sum(any(values) for values in grades.values()) / len(ids),
                complete=True,
            )
        results[benchmark] = result

    paths = {
        "hle": ROOT / f"benchmarks/hle/artifacts/{tag}/hle-original.summary.json",
        "cmt": ROOT / f"analysis/CMT-Benchmark/artifacts/{tag}/cmt-original.summary.json",
        "critpt": ROOT / f"analysis/CritPt/artifacts/{tag}/critpt-original.summary.json",
    }
    for benchmark, path in paths.items():
        summary = read_json(path, {})
        results[benchmark] = {
            "questions": summary.get("questions"),
            "mean_at_4": summary.get("mean_score", summary.get("final_score")),
            "pass_at_4": summary.get("max_score"),
            "complete": bool(summary.get("complete")),
        }
    report = {
        "model": model_id,
        "reasoning_effort": "max",
        "judge_model": "gpt-5.6-sol",
        "judge_reasoning_effort": "high",
        "protocol": "Original benchmark prompts and evaluators; four fresh no-tool attempts.",
        "results": results,
        "complete": all(value["complete"] for value in results.values()),
    }
    atomic_json(run / "native-original/suite-summary.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=MODELS, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--served-model", help="Provider route/model slug; defaults to the HF model ID")
    parser.add_argument("--manifest-base-url", help="Stable manifest route when resuming after a provider change")
    parser.add_argument("--manifest-model", help="Stable manifest model when resuming after a provider change")
    parser.add_argument("--transport-timeout", type=int, default=10800,
                        help="HTTP transport timeout; excluded from the scientific manifest")
    parser.add_argument("--generation-workers", type=int, default=14)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--stage", choices=("prepare", "all", "summary"), default="all")
    args = parser.parse_args()
    if args.generation_workers < 1 or args.retries < 0:
        parser.error("Workers must be positive and retries nonnegative")

    model, model_id, tag, model_root = MODELS[args.model]
    run = model_root / "runs" / tag
    native = run / "native-original" / args.model
    logs = run / "native-original/logs"
    logs.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "OPENAI_COMPAT_BASE_URL": args.base_url,
        "OPENAI_COMPAT_MODEL": args.served_model or model_id,
        "OPENAI_COMPAT_TIMEOUT_OVERRIDE": str(args.transport_timeout),
    }
    if args.manifest_base_url:
        env["OPENAI_COMPAT_MANIFEST_BASE_URL"] = args.manifest_base_url
    if args.manifest_model:
        env["OPENAI_COMPAT_MANIFEST_MODEL"] = args.manifest_model
    crit_generation_workers = 64 if args.model == "deepseek" else 24
    hle_workers = 416 if args.model == "deepseek" else 128
    cmt_workers = 128 if args.model == "deepseek" else 32
    plan = {
        "model": model_id,
        "generation_calls": 2428,
        "selected_100_calls": 1200,
        "hle_calls": 808,
        "cmt_calls": 200,
        "critpt_calls": 220,
        "phase_a_generation_clients": args.generation_workers * 12 + crit_generation_workers,
        "phase_b_generation_clients": hle_workers + cmt_workers,
    }
    atomic_json(run / "native-original/plan.json", plan)
    if args.stage == "prepare":
        print(json.dumps(plan, indent=2))
        return 0
    if args.stage == "summary":
        report = summarize(run, args.model, model_id, tag)
        print(json.dumps(report, indent=2))
        return 0 if report["complete"] else 2

    failed = {}
    phase_a = []
    for benchmark in ("phybench", "prism", "ugphysics"):
        for attempt in range(1, 5):
            output = native / benchmark / f"attempt-{attempt}"
            name = f"{benchmark}-attempt-{attempt}-generate"
            phase_a.append((
                name,
                local_command(run / "native-original", args.model, benchmark, attempt, "generate",
                              args.generation_workers, 4, 16),
                logs / f"{benchmark}-attempt-{attempt}.log",
                lambda output=output: count(output / "predictions.json") == 100,
            ))

    crit_output = ROOT / f"analysis/CritPt/artifacts/{tag}/critpt-original.json"
    crit_generate = [
        str(PYTHON), "-u", str(ROOT / "analysis/CritPt/scripts/evaluate.py"),
        "--dataset", "original", *common(model, crit_generation_workers), "--limit-policy", "incorrect",
        "--judge-max-output-tokens", "32768", "--stage", "generate", "--output", str(crit_output),
    ]
    phase_a.append((
        "critpt-generate", crit_generate, logs / "critpt-original.log",
        lambda: read_json(crit_output.with_suffix(".summary.json"), {}).get("missing_predictions") == 0,
    ))
    failed.update({name: code for name, code in run_batch(phase_a, args.retries, env).items() if code})
    if failed:
        atomic_json(run / "native-original/exit-codes.json", failed)
        return 2

    phase_b = []
    for benchmark in ("phybench", "prism", "ugphysics"):
        for attempt in range(1, 5):
            output = native / benchmark / f"attempt-{attempt}"
            name = f"{benchmark}-attempt-{attempt}-score"
            phase_b.append((
                name,
                local_command(run / "native-original", args.model, benchmark, attempt, "score",
                              args.generation_workers, 4, 16),
                logs / f"{benchmark}-attempt-{attempt}.log",
                lambda output=output: count(output / "scores.json") == 100,
            ))

    hle_output = ROOT / f"benchmarks/hle/artifacts/{tag}/hle-original.json"
    hle = [
        str(PYTHON), "-u", str(ROOT / "benchmarks/hle/evaluate.py"),
        "--dataset", str(FROZEN / "hle-original.json"), "--category", "Physics",
        "--no-include-images", "--limit-policy", "incorrect", *common(model, hle_workers),
        "--output", str(hle_output),
    ]
    phase_b.append(("hle-original", hle, logs / "hle-original.log",
                    lambda: native_summary_complete(hle_output.with_suffix(".summary.json"))))

    cmt_output = ROOT / f"analysis/CMT-Benchmark/artifacts/{tag}/cmt-original.json"
    cmt = [
        str(PYTHON), "-u", str(ROOT / "analysis/CMT-Benchmark/evaluate.py"),
        "--dataset", str(ROOT / "analysis/CMT-Benchmark/data/cmt_data_original.jsonl"),
        *common(model, cmt_workers), "--output", str(cmt_output),
    ]
    phase_b.append(("cmt-original", cmt, logs / "cmt-original.log",
                    lambda: native_summary_complete(cmt_output.with_suffix(".summary.json"))))

    crit_judge = [
        str(PYTHON), "-u", str(ROOT / "analysis/CritPt/scripts/evaluate.py"),
        "--dataset", "original", *common(model, 32), "--limit-policy", "incorrect",
        "--judge-max-output-tokens", "32768", "--stage", "judge", "--output", str(crit_output),
    ]
    phase_b.append(("critpt-judge", crit_judge, logs / "critpt-original.log",
                    lambda: native_summary_complete(crit_output.with_suffix(".summary.json"))))
    failed.update({name: code for name, code in run_batch(phase_b, args.retries, env).items() if code})

    if not failed:
        auxiliary = []
        for attempt in range(1, 5):
            output = native / "ugphysics" / f"attempt-{attempt}"
            auxiliary.append((
                f"ugphysics-attempt-{attempt}-auxiliary",
                local_command(run / "native-original", args.model, "ugphysics", attempt, "auxiliary",
                              args.generation_workers, 4, 32),
                logs / f"ugphysics-attempt-{attempt}.log",
                lambda output=output: native_summary_complete(output / "summary.json"),
            ))
        failed.update({name: code for name, code in run_batch(auxiliary, args.retries, env).items() if code})

    atomic_json(run / "native-original/exit-codes.json", failed)
    report = summarize(run, args.model, model_id, tag)
    print(json.dumps(report, indent=2))
    return 0 if not failed and report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
