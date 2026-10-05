#!/usr/bin/env python3
"""Run and resume the frozen Kimi K3 max-reasoning physics evaluation suite."""

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
PYTHON = ROOT / "model_evals/gemini/.venv/bin/python"
TAG = "kimi-k3-max-no-tools-20260917"
RUN = ROOT / "model_evals/kimi/runs" / TAG
GEMINI = ROOT / "model_evals/gemini/runs/gemini31-20260908"
FROZEN = GEMINI / "repeated"
MODEL = "kimi-k3"
MODEL_ID = "moonshotai/Kimi-K3"
TEMPERATURE = 1.0
TOP_P = 0.95
JUDGE = "gpt-5.6-sol"
BENCHMARKS = ("phybench", "prism", "ugphysics")


def read_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def original_jobs(workers: int) -> dict[str, list[str]]:
    jobs = {}
    native = RUN / "native-original"
    for benchmark in BENCHMARKS:
        for attempt in range(1, 5):
            jobs[f"native-{benchmark}-{attempt}"] = [
                str(PYTHON), "-u", "-m", "eval.suites.native_selected_mean4",
                "--output", str(native), "--model", "kimi", "--benchmark", benchmark,
                "--attempt", str(attempt), "--stage", "all", "--workers", str(workers),
                "--score-workers", "4", "--judge-workers", "8", "--grade-timeout", "180",
                "--timeout", "3600",
            ]
    common = ["--model", MODEL, "--judge-model", JUDGE,
              "--reasoning-effort", "max", "--judge-reasoning-effort", "high",
              "--rounds", "4", "--aggregation", "mean", "--num-workers", str(workers * 2),
              "--round-workers", "4", "--timeout", "3600", "--max-output-tokens", "65536",
              "--no-use-tools", "--web-search", "disabled"]
    jobs["hle-original"] = [
        str(PYTHON), "-u", str(ROOT / "benchmarks/hle/evaluate.py"),
        "--dataset", str(FROZEN / "hle-original.json"), "--category", "Physics",
        "--no-include-images", "--limit-policy", "incorrect", *common,
        "--output", str(ROOT / f"benchmarks/hle/artifacts/{TAG}/hle-original.json"),
    ]
    for split, source in (("original", "cmt_data_original.jsonl"),
                          ("corrected", "cmt_data_clean.json")):
        command = [
            str(PYTHON), "-u", str(ROOT / "analysis/CMT-Benchmark/evaluate.py"),
            "--dataset", str(ROOT / "analysis/CMT-Benchmark/data" / source), *common,
            "--output", str(ROOT / f"analysis/CMT-Benchmark/artifacts/{TAG}/cmt-{split}.json"),
        ]
        if split == "corrected":
            command += ["--ids-file", str(FROZEN / "cmt-corrected-ids.json")]
        jobs[f"cmt-{split}"] = command
    for split in ("original", "corrected"):
        jobs[f"critpt-{split}"] = [
            str(PYTHON), "-u", str(ROOT / "analysis/CritPt/scripts/evaluate.py"),
            "--dataset", split, *common, "--limit-policy", "incorrect",
            "--judge-max-output-tokens", "32768",
            "--output", str(ROOT / f"analysis/CritPt/artifacts/{TAG}/critpt-{split}.json"),
        ]
    return jobs


def corrected_import(benchmark: str, attempt: int) -> Path:
    source = RUN / "native-original/kimi" / benchmark / f"attempt-{attempt}"
    target = RUN / "corrected-imports" / benchmark / f"attempt-{attempt}"
    corrected = read_json(GEMINI / benchmark / "corrected/dataset.json")
    predictions = read_json(source / "predictions.json", {})
    selected = {}
    for row in corrected:
        prediction = predictions[row["id"]]
        response = prediction.get("final_answer") if benchmark == "phybench" else None
        selected[row["id"]] = {**prediction, "response": response or prediction["response"]}
    manifest = {"format": "normalized-predictions-v1", "model": MODEL,
                "reasoning_effort": "max", "tools": False}
    write_json(target / "manifest.json", manifest)
    write_json(target / "dataset.json", corrected)
    write_json(target / "predictions.json", selected)
    return target


def corrected_jobs(workers: int) -> dict[str, list[str]]:
    jobs = {}
    for benchmark in BENCHMARKS:
        data = GEMINI / benchmark / "corrected/dataset.json"
        for attempt in range(1, 5):
            imported = corrected_import(benchmark, attempt)
            jobs[f"corrected-{benchmark}-{attempt}"] = [
                str(PYTHON), "-u", "-m", "eval",
                "--dataset", f"{benchmark}-frozen-gemini-corrected", "--data", str(data),
                "--split", "corrected", "--predictions-from", str(imported),
                "--output", str(RUN / "corrected" / benchmark / f"attempt-{attempt}"),
                "--model", MODEL, "--judge-model", JUDGE,
                "--reasoning-effort", "max", "--judge-reasoning-effort", "high",
                "--mode", "merged", "--max-output-tokens", "65536",
                "--judge-max-output-tokens", "32768", "--timeout", "3600",
                "--workers", str(workers),
            ]
    return jobs


def run_jobs(jobs: dict[str, list[str]], retries: int, parallel: int) -> dict[str, int]:
    logs = RUN / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    write_json(RUN / "commands.json", {**read_json(RUN / "commands.json", {}), **jobs})

    def execute(name: str, command: list[str]) -> tuple[str, int]:
        code = 2
        for invocation in range(1, retries + 2):
            with (logs / f"{name}.log").open("a") as stream:
                stream.write(f"\nInvocation {invocation}: {json.dumps(command)}\n")
                stream.flush()
                code = subprocess.run(command, cwd=ROOT, stdout=stream,
                                      stderr=subprocess.STDOUT).returncode
            if code == 0:
                break
            if invocation <= retries:
                time.sleep(30)
        return name, code

    codes = {}
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = [pool.submit(execute, name, command) for name, command in jobs.items()]
        for future in as_completed(futures):
            name, code = future.result()
            codes[name] = code
            write_json(RUN / "exit-codes.json", {**read_json(RUN / "exit-codes.json", {}), name: code})
            print(f"{name}: exit {code}", flush=True)
    return codes


def rejudge_hle_corrected() -> None:
    sys.path.insert(0, str(ROOT / "benchmarks/hle"))
    from hle_eval import runner
    from hle_eval.scoring import judge_round

    original = ROOT / f"benchmarks/hle/artifacts/{TAG}/hle-original.json"
    rows = read_json(FROZEN / "hle-corrected.json")
    ids = {row["id"] for row in rows}
    questions = [{key: row[key] for key in ("id", "question", "category", "image")} for row in rows]
    answers = {row["id"]: row["answer"] for row in rows}
    args = runner.parse_args([
        "--dataset", str(FROZEN / "hle-original.json"), "--category", "Physics",
        "--model", MODEL, "--judge-model", JUDGE, "--reasoning-effort", "max",
        "--judge-reasoning-effort", "high", "--rounds", "4", "--aggregation", "mean",
        "--num-workers", "24", "--round-workers", "4", "--timeout", "3600",
        "--max-output-tokens", "65536", "--no-use-tools", "--web-search", "disabled",
        "--output", str(original),
    ])
    args.num_workers = 6

    def judge(number: int):
        suffix = "" if number == 1 else f".round{number}"
        predictions = read_json(original.with_name(original.stem + suffix + ".json"), {})
        predictions = {qid: value for qid, value in predictions.items() if qid in ids}
        output = original.with_name("hle-corrected" + suffix + ".judged.json")
        return judge_round(args, questions, answers, predictions, output, write_json)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(judge, range(1, 5)))


def aggregate_four(per_attempt: list[list[dict]]) -> dict:
    ids = [row["id"] for row in per_attempt[0]]
    maps = [{row["id"]: bool(row["correct"]) for row in rows} for rows in per_attempt]
    grades = {qid: [int(values[qid]) for values in maps] for qid in ids}
    return {"questions": len(ids), "mean@4": sum(map(sum, grades.values())) / (4 * len(ids)),
            "pass@4": sum(any(values) for values in grades.values()) / len(ids),
            "per_question": grades}


def summarize() -> dict:
    results = {}
    for benchmark in BENCHMARKS:
        original = [read_json(RUN / "native-original/kimi" / benchmark /
                              f"attempt-{attempt}/summary.json", {}) for attempt in range(1, 5)]
        corrected = [read_json(RUN / "corrected" / benchmark /
                               f"attempt-{attempt}/summary.json", {}) for attempt in range(1, 5)]
        if all(row.get("complete") for row in original):
            results[f"{benchmark}/original"] = aggregate_four([row["per_question"] for row in original])
        if all(row.get("complete") for row in corrected):
            results[f"{benchmark}/corrected"] = aggregate_four([row["per_question"] for row in corrected])
    hle_original = read_json(ROOT / f"benchmarks/hle/artifacts/{TAG}/hle-original.summary.json", {})
    if hle_original.get("complete"):
        results["hle/original"] = {"questions": hle_original["questions"],
                                   "mean@4": hle_original["mean_score"],
                                   "pass@4": hle_original["max_score"]}
    corrected_ids = [row["id"] for row in read_json(FROZEN / "hle-corrected.json", [])]
    corrected_rounds = []
    hle_dir = ROOT / f"benchmarks/hle/artifacts/{TAG}"
    for number in range(1, 5):
        suffix = "" if number == 1 else f".round{number}"
        corrected_rounds.append(read_json(hle_dir / f"hle-corrected{suffix}.judged.json", {}))
    if corrected_ids and all(len(row) == len(corrected_ids) for row in corrected_rounds):
        sys.path.insert(0, str(ROOT / "benchmarks/hle"))
        from hle_eval.scoring import aggregate_scores
        row = aggregate_scores(corrected_ids, corrected_rounds, "mean")
        if row.get("complete"):
            results["hle/corrected"] = {"questions": row["questions"],
                                        "mean@4": row["mean_score"],
                                        "pass@4": row["max_score"]}
    for benchmark, base in (("cmt", ROOT / f"analysis/CMT-Benchmark/artifacts/{TAG}"),
                            ("critpt", ROOT / f"analysis/CritPt/artifacts/{TAG}")):
        for split in ("original", "corrected"):
            row = read_json(base / f"{benchmark}-{split}.summary.json", {})
            if row.get("complete"):
                results[f"{benchmark}/{split}"] = {"questions": row["questions"],
                                                    "mean@4": row["mean_score"],
                                                    "pass@4": row["max_score"]}
    summary = {"model": MODEL_ID, "reasoning_effort": "max", "tools": False,
               "judge_model": JUDGE, "judge_reasoning_effort": "high", "results": results,
               "complete": len(results) == 12}
    write_json(RUN / "suite-summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--judge-workers", type=int, default=16)
    parser.add_argument("--parallel", type=int, default=17)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--stage", choices=["prepare", "all", "summary"], default="all")
    args = parser.parse_args()
    if min(args.workers, args.judge_workers, args.parallel) < 1 or args.retries < 0:
        parser.error("Worker counts must be positive and retries nonnegative")
    RUN.mkdir(parents=True, exist_ok=True)
    write_json(RUN / "protocol.json", {
        "model": MODEL_ID, "reasoning_effort": "max", "temperature": TEMPERATURE,
        "top_p": TOP_P, "max_output_tokens": 65536, "tools": False,
        "judge_model": JUDGE, "judge_reasoning_effort": "high",
        "attempts": 4, "frozen_inputs": str(GEMINI),
    })
    if args.stage == "summary":
        print(json.dumps(summarize(), indent=2))
        return 0
    jobs = original_jobs(args.workers)
    if args.stage == "prepare":
        write_json(RUN / "commands.json", jobs)
        print(json.dumps({"jobs": len(jobs), "generation_calls": 2840}, indent=2))
        return 0
    codes = run_jobs(jobs, args.retries, args.parallel)
    if any(codes.values()):
        summarize()
        return 2
    rejudge_hle_corrected()
    codes.update(run_jobs(corrected_jobs(args.judge_workers), args.retries, 12))
    value = summarize()
    print(json.dumps(value, indent=2))
    return 0 if value["complete"] and not any(codes.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
