#!/usr/bin/env python3
"""Run corrected GPT-OSS tool evaluations through the Codex harness."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parents[2]
TAG = "gpt-oss-120b-high-tools-corrected-20260914"
RUN = ROOT / "model_evals/gpt_oss/runs" / TAG
SOURCE = ROOT / "model_evals/gemini/runs/gemini31-20260908/repeated"
PYTHON = ROOT / "model_evals/gemini/.venv/bin/python"


def commands(workers: int) -> dict[str, list[str]]:
    common = ["--model", "gpt-oss-120b", "--judge-model", "claude-fable-5",
              "--reasoning-effort", "high", "--judge-reasoning-effort", "high",
              "--rounds", "4", "--aggregation", "mean", "--num-workers", str(workers),
              "--timeout", "3600", "--use-tools", "--web-search", "live"]
    return {
        "hle": [str(PYTHON), "-u", str(ROOT / "benchmarks/hle/evaluate.py"),
                "--dataset", str(SOURCE / "hle-corrected.json"), "--category", "Physics",
                "--no-include-images", *common, "--round-workers", "4",
                "--limit-policy", "incorrect", "--output",
                str(ROOT / f"benchmarks/hle/artifacts/{TAG}/hle-corrected-tools.json")],
        "cmt": [str(PYTHON), "-u", str(ROOT / "analysis/CMT-Benchmark/evaluate.py"),
                "--dataset", str(ROOT / "analysis/CMT-Benchmark/data/cmt_data_clean.json"),
                "--ids-file", str(SOURCE / "cmt-corrected-ids.json"), *common, "--output",
                str(ROOT / f"analysis/CMT-Benchmark/artifacts/{TAG}/cmt-corrected-tools.json")],
        "critpt": [str(PYTHON), "-u", str(ROOT / "analysis/CritPt/scripts/evaluate.py"),
                   "--dataset", "corrected", *common, "--round-workers", "4",
                   "--limit-policy", "incorrect", "--output",
                   str(ROOT / f"analysis/CritPt/artifacts/{TAG}/critpt-corrected-tools.json")],
    }


def summary_path(name: str, command: list[str]) -> Path:
    return Path(command[command.index("--output") + 1]).with_suffix(".summary.json")


def main() -> int:
    workers = int(os.environ.get("GPT_OSS_TOOL_WORKERS", "80"))
    python_path = [str(ROOT), str(ROOT / "utils")]
    if os.environ.get("PYTHONPATH"):
        python_path.append(os.environ["PYTHONPATH"])
    child_env = {**os.environ, "PYTHONPATH": os.pathsep.join(python_path)}
    RUN.mkdir(parents=True, exist_ok=True)
    logs = RUN / "logs"
    logs.mkdir(exist_ok=True)
    jobs = commands(workers)
    (RUN / "commands.json").write_text(json.dumps(jobs, indent=2) + "\n")
    codes = {}
    pending = set(jobs)
    for invocation in range(1, 5):
        running = {}
        streams = {}
        for name in sorted(pending):
            command = jobs[name]
            stream = (logs / f"{name}.log").open("a")
            streams[name] = stream
            stream.write(f"\nInvocation {invocation}: " + json.dumps(command) + "\n")
            stream.flush()
            running[name] = subprocess.Popen(
                command,
                cwd=ROOT,
                env=child_env,
                stdout=stream,
                stderr=subprocess.STDOUT,
            )
        for name, process in running.items():
            codes[name] = process.wait()
        for stream in streams.values():
            stream.close()
        pending = {name for name, command in jobs.items()
                   if not (summary_path(name, command).exists() and
                           json.loads(summary_path(name, command).read_text()).get("complete"))}
        if not pending:
            break
        if invocation < 4:
            time.sleep(30)
    results = {}
    for name, command in jobs.items():
        path = summary_path(name, command)
        results[name] = json.loads(path.read_text()) if path.exists() else {"complete": False}
    report = {"model": "gpt-oss-120b", "reasoning_effort": "high", "tools": True,
              "tool_harness": "codex exec", "web_search": "live",
              "judge_model": "claude-fable-5", "judge_reasoning_effort": "high",
              "workers_per_benchmark": workers, "returncodes": codes, "results": results,
              "complete": all(value.get("complete") for value in results.values())}
    (RUN / "suite-summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
