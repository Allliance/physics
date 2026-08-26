#!/usr/bin/env python3
"""Rerun a CritPt problem with the shell environment inherited, so Python is on PATH.

Everything else matches run_codex_cli_eval.py. The point is to isolate one
variable: does the model use code execution when an interpreter actually exists?
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PHYSICS_ROOT = Path("/shared/data/home/aa3242/physics")
sys.path[:0] = [str(ROOT / "src"), str(PHYSICS_ROOT)]

from critpt.data_loader import JsonDataLoader
from critpt.generation.prompts import PromptBuilder, build_system_prompt
from utils.codex_cli import CodexLLM


class InheritEnvCodexLLM(CodexLLM):
    """CodexLLM with shell_environment_policy.inherit flipped from "none" to "all"."""

    def _build_command(self, cwd, output_schema, image_paths):
        cmd = super()._build_command(cwd, output_schema, image_paths)
        for i, part in enumerate(cmd):
            if part == 'shell_environment_policy.inherit="none"':
                cmd[i] = 'shell_environment_policy.inherit="all"'
                break
        else:
            raise RuntimeError("inherit=none flag not found; wrapper changed upstream")
        return cmd


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--challenge", type=int, required=True)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "results" / "codex_cli_probe_python_on_path")
    args = parser.parse_args()

    path = ROOT / "data" / "public_test_challenges" / "json" / f"Challenge_{args.challenge}.json"
    if not path.exists():
        raise SystemExit(f"missing {path}")

    loader = JsonDataLoader(path)
    problem = loader.load_main_problem()
    prompt = PromptBuilder(loader.get_reader(), False, False, False).main_step().prompt
    system_prompt = build_system_prompt(False, True, True)

    client = InheritEnvCodexLLM(
        model=args.model,
        model_reasoning_effort=args.reasoning_effort,
        codex_bin=str(ROOT / "codex_isolated"),
        timeout=args.timeout,
        strict_no_tools=False,
        web_search="live",
    )

    out_dir = args.output_dir / args.model / args.reasoning_effort / "0"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"generating {problem.problem_id} with PATH inherited", flush=True)
    result = client.complete(prompt, system_prompt=system_prompt)

    (out_dir / f"{problem.problem_id}.json").write_text(
        json.dumps({"problem_id": problem.problem_id, "generated_code": result.text}, indent=2),
        encoding="utf-8",
    )
    (out_dir / f"{problem.problem_id}.usage.json").write_text(
        json.dumps({"usage": result.usage, "attempts": result.attempts}, indent=2),
        encoding="utf-8",
    )
    with (out_dir / f"{problem.problem_id}.events.jsonl").open("w", encoding="utf-8") as handle:
        for event in result.events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    print(f"saved {problem.problem_id} ({len(result.events)} events)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
