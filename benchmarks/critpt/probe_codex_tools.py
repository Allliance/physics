#!/usr/bin/env python3
"""Repeatedly exercise every Codex tool and verify from the event stream.

This does not trust the model's prose. It parses the raw `codex exec --json`
events and checks that commands actually ran, exited 0, and produced the
expected stdout markers.

    python3 probe_codex_tools.py --runs 3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PHYSICS_ROOT = Path("/shared/data/home/aa3242/physics")
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(PHYSICS_ROOT)]

from codex_tools_config import TOOLS_PROMPT_SUFFIX, codex_tool_kwargs
from utils.codex_cli import CodexLLM


PROBE_PROMPT = """Verify your computational environment by actually running commands. Do all of the following:

1. Run `python3 -c` printing the versions of numpy, scipy, sympy, mpmath, pandas and qutip, each on its own line prefixed with `VERSION `.
2. Use scipy to compute the integral of exp(-x^2) from 0 to 1 numerically; print it as `QUAD <value>` with 12 decimals.
3. Use sympy to symbolically solve x**2 - 5*x + 6 = 0 and print `SYMPY <roots>`.
4. Use mpmath at 40-digit precision to print `MPMATH <value>` for zeta(3).
5. Write a scratch file `check.py` in the current directory that prints the 10th Fibonacci number, then run it with python3 and print `FILE <value>`.
6. Use numpy to compute the largest eigenvalue of [[2,1],[1,3]] and print `EIG <value>` with 10 decimals.
7. Use the web_search tool once to look up the accepted value of Apery's constant, and compare it to your mpmath result.

Then reply with a single JSON object (no code fences) with keys: versions, quad, sympy, mpmath, file, eig, websearch_agrees.
"""

EXPECTED_MARKERS = ["VERSION", "QUAD", "SYMPY", "MPMATH", "FILE", "EIG"]


def analyse(events: list[dict]) -> dict:
    commands, searches, failures = [], [], []
    stdout_all: list[str] = []
    for event in events:
        item = event.get("item") or {}
        if event.get("type") != "item.completed":
            continue
        if item.get("type") == "command_execution":
            commands.append(item)
            out = item.get("aggregated_output") or ""
            stdout_all.append(out)
            if item.get("exit_code") not in (0, None):
                failures.append({"command": item.get("command"), "exit_code": item.get("exit_code"),
                                 "output": out[-400:]})
        elif item.get("type") == "web_search":
            searches.append((item.get("action") or {}).get("queries") or [item.get("query")])
    blob = "\n".join(stdout_all)
    return {
        "n_commands": len(commands),
        "n_failed_commands": len(failures),
        "failures": failures,
        "n_searches": len(searches),
        "queries": searches,
        "markers_found": {m: (m in blob) for m in EXPECTED_MARKERS},
        "interpreter_missing": "command not found" in blob,
        "import_error": "ModuleNotFoundError" in blob,
        "stdout_blob": blob,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--log-dir", type=Path, default=ROOT / "results" / "codex_tool_probes")
    args = parser.parse_args()

    args.log_dir.mkdir(parents=True, exist_ok=True)
    client = CodexLLM(
        model=args.model,
        model_reasoning_effort=args.reasoning_effort,
        codex_bin=str(ROOT / "codex_isolated"),
        timeout=args.timeout,
        strict_no_tools=False,
        web_search="live",
        **codex_tool_kwargs(),
    )
    system_prompt = ("You are a careful computational physics assistant." + TOOLS_PROMPT_SUFFIX)

    summaries = []
    for run in range(1, args.runs + 1):
        print(f"--- probe run {run}/{args.runs}", flush=True)
        result = client.complete(PROBE_PROMPT, system_prompt=system_prompt)
        report = analyse(result.events)
        report["run"] = run
        report["usage"] = result.usage
        report["final_text"] = result.text

        (args.log_dir / f"run_{run}.events.jsonl").write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in result.events), encoding="utf-8")
        (args.log_dir / f"run_{run}.report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

        ok = (report["n_commands"] > 0 and report["n_failed_commands"] == 0
              and all(report["markers_found"].values()) and not report["interpreter_missing"]
              and not report["import_error"] and report["n_searches"] > 0)
        report["pass"] = ok
        summaries.append(report)
        print(f"    commands={report['n_commands']} failed={report['n_failed_commands']} "
              f"searches={report['n_searches']} markers={sum(report['markers_found'].values())}/6 "
              f"-> {'PASS' if ok else 'FAIL'}", flush=True)
        if not ok and report["failures"]:
            print("    first failure:", json.dumps(report["failures"][0])[:400], flush=True)

    n_pass = sum(1 for s in summaries if s["pass"])
    print(f"\n=== {n_pass}/{len(summaries)} probe runs passed; logs in {args.log_dir}")
    return 0 if n_pass == len(summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
