#!/usr/bin/env python3
"""Run CritPt problems through the Codex CLI and persist the full event trace.

Mirrors run_codex_cli_eval.py's configuration exactly, but additionally writes
the raw `codex exec --json` event stream (tool calls, web searches, reasoning
summaries) to `<problem_id>.events.jsonl` so tool usage can be audited.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PHYSICS_ROOT = Path("/shared/data/home/aa3242/physics")
sys.path[:0] = [str(ROOT / "src"), str(PHYSICS_ROOT)]

from critpt.data_loader import JsonDataLoader
from critpt.generation.prompts import PromptBuilder, build_system_prompt
from critpt.submission import create_submission
from utils.codex_cli import CodexLLM

sys.path.insert(0, str(ROOT))
from codex_tools_config import TOOLS_PROMPT_SUFFIX, codex_tool_kwargs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--challenge", type=int, action="append", required=True,
                        help="Challenge number; repeat for several.")
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--epoch", type=int, default=0)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "results" / "codex_cli_tools_web_trace")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--crippled-env", action="store_true",
                        help="Reproduce the old behaviour: no interpreter on PATH.")
    return parser.parse_args()


def challenge_number(path: Path) -> int:
    return int(path.stem.removeprefix("Challenge_"))


def main() -> int:
    args = parse_args()
    all_paths = sorted(
        (ROOT / "data" / "public_test_challenges" / "json").glob("Challenge_*.json"),
        key=challenge_number,
    )
    wanted = set(args.challenge)
    paths = [p for p in all_paths if challenge_number(p) in wanted]
    missing = wanted - {challenge_number(p) for p in paths}
    if missing:
        raise SystemExit(f"Challenges not found: {sorted(missing)}")

    tool_kwargs = {} if args.crippled_env else codex_tool_kwargs()
    client = CodexLLM(
        model=args.model,
        model_reasoning_effort=args.reasoning_effort,
        codex_bin=str(ROOT / "codex_isolated"),
        timeout=args.timeout,
        strict_no_tools=False,
        web_search="live",
        **tool_kwargs,
    )
    config = {
        "use_golden_for_prev_steps": False,
        "parsing": False,
        "multiturn_with_answer": False,
        "use_python": not args.crippled_env,
        "use_web_search": True,
        "reasoning_effort": args.reasoning_effort,
        "generator": "physics/utils/codex_cli",
        "traced": True,
        "tool_env": "crippled" if args.crippled_env else "codex_tools_env",
    }
    system_prompt = build_system_prompt(False, True, True)
    if not args.crippled_env:
        system_prompt += TOOLS_PROMPT_SUFFIX

    epoch_dir = args.output_dir / args.model / args.reasoning_effort / str(args.epoch)
    epoch_dir.mkdir(parents=True, exist_ok=True)

    def generate_one(index_path: tuple[int, Path]) -> Path:
        index, path = index_path
        loader = JsonDataLoader(path)
        problem = loader.load_main_problem()
        output_path = epoch_dir / f"{problem.problem_id}.json"
        usage_path = epoch_dir / f"{problem.problem_id}.usage.json"
        events_path = epoch_dir / f"{problem.problem_id}.events.jsonl"
        if output_path.exists() and not args.overwrite:
            print(f"[{index}/{len(paths)}] skip {problem.problem_id} (already exists)", flush=True)
            return output_path

        reader = loader.get_reader()
        prompt = PromptBuilder(reader, False, False, False).main_step().prompt
        print(f"[{index}/{len(paths)}] generating {problem.problem_id}", flush=True)
        result = client.complete(prompt, system_prompt=system_prompt)
        submission = create_submission(
            problem_id=problem.problem_id,
            generated_code=result.text,
            model=f"codex-cli/{args.model}",
            generation_config=config,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": result.text},
            ],
        )
        submission.to_json(output_path)
        usage_path.write_text(
            json.dumps({"usage": result.usage, "attempts": result.attempts}, indent=2),
            encoding="utf-8",
        )
        with events_path.open("w", encoding="utf-8") as handle:
            for event in result.events:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        if result.workspace_files:
            ws_dir = epoch_dir / f"{problem.problem_id}.workspace"
            for rel, text in result.workspace_files.items():
                dest = ws_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8")
        print(f"[{index}/{len(paths)}] saved {output_path} "
              f"({len(result.events)} events)", flush=True)
        return output_path

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(generate_one, item) for item in enumerate(paths, 1)]
        for future in concurrent.futures.as_completed(futures):
            future.result()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
