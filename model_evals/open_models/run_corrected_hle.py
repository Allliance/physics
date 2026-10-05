#!/usr/bin/env python3
"""Run four fresh HLE-adapted corrected attempts for the open models."""

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
    "kimi-k3": ("moonshotai/Kimi-K3", ROOT / "model_evals/kimi/runs/kimi-k3-max-no-tools-20260917"),
    "glm-5.3": ("zai-org/GLM-5.3", ROOT / "model_evals/glm/runs/glm-5.3-max-no-tools-20260917"),
    "deepseek-v4-pro": (
        "deepseek-ai/DeepSeek-V4-Pro",
        ROOT / "model_evals/deepseek/runs/deepseek-v4-pro-max-no-tools-20260917",
    ),
}
COUNTS = {"phybench": 88, "prism": 74, "ugphysics": 78, "hle": 115, "cmt": 49, "critpt": 54}


def read_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def prepare_cmt_subset(run: Path) -> Path:
    source = ROOT / "analysis/CMT-Benchmark/data/cmt_data_clean.json"
    ids_path = FROZEN / "cmt-corrected-ids.json"
    rows = read_json(source)
    ids = read_json(ids_path)
    by_id = {str(row["index"]): row for row in rows}
    missing = [qid for qid in ids if qid not in by_id]
    if missing:
        raise ValueError(f"CMT corrected IDs missing from source: {missing}")
    selected = [by_id[qid] for qid in ids]
    path = run / "inputs/cmt-corrected-49.json"
    if path.exists() and read_json(path) != selected:
        raise ValueError(f"Frozen CMT input changed: {path}")
    atomic_json(path, selected)
    return path


def datasets(run: Path) -> dict[str, tuple[str, Path]]:
    return {
        "phybench": ("phybench-frozen-gemini-corrected", GEMINI / "phybench/corrected/dataset.json"),
        "prism": ("prism-frozen-gemini-corrected", GEMINI / "prism/corrected/dataset.json"),
        "ugphysics": ("ugphysics-frozen-gemini-corrected", GEMINI / "ugphysics/corrected/dataset.json"),
        "hle": ("hle-frozen-gemini-corrected", FROZEN / "hle-corrected.json"),
        "cmt": ("cmt-frozen-gemini-corrected", prepare_cmt_subset(run)),
        "critpt": ("critpt-corrected", ROOT / "analysis/CritPt/corrected_challenge.jsonl"),
    }


def command(model: str, dataset_name: str, data: Path, output: Path, workers: int, stage: str) -> list[str]:
    return [
        str(PYTHON), "-u", "-m", "eval",
        "--dataset", dataset_name,
        "--data", str(data),
        "--split", "corrected",
        "--output", str(output),
        "--model", model,
        "--judge-model", "gpt-5.6-sol",
        "--reasoning-effort", "max",
        "--judge-reasoning-effort", "high",
        "--mode", "merged",
        "--max-output-tokens", "65536",
        "--judge-max-output-tokens", "32768",
        # Long max-reasoning traces can exceed one hour on the large MoE
        # models.  A three-hour client timeout avoids throwing away an almost
        # complete 65k-token response and retrying it from scratch.
        "--timeout", "3600",
        "--workers", str(workers),
        "--stage", stage,
    ]


def prediction_count(output: Path) -> int:
    return len(read_json(output / "predictions.json", {}))


def is_complete(output: Path) -> bool:
    return bool(read_json(output / "summary.json", {}).get("complete"))


def run_one(*, name: str, argv: list[str], log: Path, complete, retries: int, env: dict) -> tuple[str, int]:
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


def summarize(run: Path, selected: list[str], model_id: str) -> dict:
    results = {}
    for benchmark in selected:
        summaries = [read_json(run / "hle-corrected" / benchmark / f"attempt-{attempt}" / "summary.json", {})
                     for attempt in range(1, 5)]
        result = {"attempts_complete": sum(bool(row.get("complete")) for row in summaries), "complete": False}
        if all(row.get("complete") for row in summaries):
            maps = [{row["id"]: bool(row["correct"]) for row in summary["per_question"]}
                    for summary in summaries]
            ids = [row["id"] for row in summaries[0]["per_question"]]
            if any(set(values) != set(ids) for values in maps):
                raise ValueError(f"{benchmark}: attempt IDs differ")
            grades = {qid: [int(values[qid]) for values in maps] for qid in ids}
            result.update(
                questions=len(ids),
                mean_at_4=sum(map(sum, grades.values())) / (4 * len(ids)),
                pass_at_4=sum(any(values) for values in grades.values()) / len(ids),
                complete=True,
            )
        results[benchmark] = result
    report = {
        "model": model_id,
        "reasoning_effort": "max",
        "judge_model": "gpt-5.6-sol",
        "judge_reasoning_effort": "high",
        "evaluator": "HLE-adapted physics equivalence; merged binary score",
        "attempts": 4,
        "results": results,
        "complete": all(value["complete"] for value in results.values()),
    }
    atomic_json(run / "hle-corrected/summary.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=MODELS, required=True)
    parser.add_argument("--benchmarks", nargs="+", choices=tuple(COUNTS), default=list(COUNTS))
    parser.add_argument("--generation-workers", type=int, default=8,
                        help="Workers per attempt; 20 runs at the default provide 160 clients.")
    parser.add_argument("--judge-workers", type=int, default=8)
    parser.add_argument("--parallel", type=int, default=24)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--served-model", help="Provider route/model slug; defaults to the HF model ID")
    parser.add_argument("--manifest-base-url", help="Stable manifest route when resuming after a provider change")
    parser.add_argument("--manifest-model", help="Stable manifest model when resuming after a provider change")
    parser.add_argument("--transport-timeout", type=int, default=10800,
                        help="HTTP transport timeout; excluded from the scientific manifest")
    parser.add_argument("--stage", choices=("prepare", "generate", "judge", "all", "summary"), default="all")
    args = parser.parse_args()
    if min(args.generation_workers, args.judge_workers, args.parallel) < 1 or args.retries < 0:
        parser.error("Worker counts must be positive and retries nonnegative")

    model_id, run = MODELS[args.model]
    selected = list(dict.fromkeys(args.benchmarks))
    sources = datasets(run)
    for benchmark in selected:
        if not sources[benchmark][1].exists():
            raise FileNotFoundError(sources[benchmark][1])
        from eval.datasets import load_dataset
        rows, _ = load_dataset(sources[benchmark][0], data=sources[benchmark][1], split="corrected")
        if len(rows) != COUNTS[benchmark]:
            raise ValueError(f"{benchmark}: expected {COUNTS[benchmark]} rows, found {len(rows)}")
    jobs = []
    for benchmark in selected:
        dataset_name, data = sources[benchmark]
        for attempt in range(1, 5):
            output = run / "hle-corrected" / benchmark / f"attempt-{attempt}"
            jobs.append((benchmark, attempt, dataset_name, data, output))
    logs = run / "hle-corrected/logs"
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

    plan = {
        "model": model_id,
        "benchmarks": {name: COUNTS[name] for name in selected},
        "attempts": 4,
        "generation_calls": sum(COUNTS[name] * 4 for name in selected),
        "generation_clients": len(jobs) * args.generation_workers,
        "judge_clients": len(jobs) * args.judge_workers,
        "base_url": args.base_url,
    }
    atomic_json(run / "hle-corrected/plan.json", plan)
    if args.stage == "prepare":
        print(json.dumps(plan, indent=2))
        return 0
    if args.stage == "summary":
        report = summarize(run, selected, model_id)
        print(json.dumps(report, indent=2))
        return 0 if report["complete"] else 2

    stages = ("generate", "judge") if args.stage == "all" else (args.stage,)
    failed = {}
    for stage in stages:
        worker_count = args.generation_workers if stage == "generate" else args.judge_workers
        futures = {}
        with ThreadPoolExecutor(max_workers=min(args.parallel, len(jobs))) as pool:
            for benchmark, attempt, dataset_name, data, output in jobs:
                expected = COUNTS[benchmark]
                complete = ((lambda output=output, expected=expected: prediction_count(output) == expected)
                            if stage == "generate" else (lambda output=output: is_complete(output)))
                name = f"{benchmark}-attempt-{attempt}-{stage}"
                argv = command(args.model, dataset_name, data, output, worker_count, stage)
                future = pool.submit(run_one, name=name, argv=argv,
                                     log=logs / f"{benchmark}-attempt-{attempt}.log",
                                     complete=complete, retries=args.retries, env=env)
                futures[future] = name
            for future in as_completed(futures):
                name, code = future.result()
                print(f"{name}: exit {code}", flush=True)
                if code:
                    failed[name] = code
        atomic_json(run / f"hle-corrected/{stage}-exit-codes.json", failed)
        if failed:
            break

    report = summarize(run, selected, model_id)
    print(json.dumps(report, indent=2))
    return 0 if not failed and (args.stage == "generate" or report["complete"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
