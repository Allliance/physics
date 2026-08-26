#!/usr/bin/env python3
"""Run CritPt's second, code-template formatting step on saved answers."""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "src"), "/shared/data/home/aa3242/physics"]

from critpt.data_loader import JsonDataLoader
from critpt.submission import create_submission
from critpt.templates import ParsePrompt
from utils.codex_cli import CodexLLM


def code_from_response(text: str) -> str:
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    return blocks[-1].strip() if blocks else text.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--challenge", type=int, action="append",
                        help="Format only this challenge; repeat for several.")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    client = CodexLLM(
        model=args.model,
        model_reasoning_effort=args.reasoning_effort,
        codex_bin=str(ROOT / "codex_isolated"),
        timeout=args.timeout,
        strict_no_tools=False,
        web_search="disabled",
    )

    def format_one(challenge: int) -> Path:
        problem_id = f"Challenge_{challenge}_main"
        source_path = args.source_dir / f"{problem_id}.json"
        output_path = args.output_dir / f"{problem_id}.json"
        usage_path = args.output_dir / f"{problem_id}.usage.json"
        if not source_path.exists():
            print(f"[{challenge}/70] skip {problem_id} (no source answer)", flush=True)
            return output_path
        if output_path.exists():
            print(f"[{challenge}/70] skip {problem_id}", flush=True)
            return output_path

        source = json.loads(source_path.read_text(encoding="utf-8"))
        loader = JsonDataLoader(
            ROOT / "data" / "public_test_challenges" / "json" / f"Challenge_{challenge}.json"
        )
        template = loader.load_main_problem().code_template
        parse_instruction = ParsePrompt.default_system_prompt(code_template=template)
        prompt = (
            "Previous solution:\n\n"
            + source["generated_code"]
            + "\n\nFormatting instruction:\n\n"
            + parse_instruction
        )
        print(f"[{challenge}/70] formatting {problem_id}", flush=True)
        result = client.complete(
            prompt,
            system_prompt=(
                "Perform only the requested code-template formatting step. "
                "Return the completed Python code and no new derivation."
            ),
        )
        code = code_from_response(result.text)
        ast.parse(code)
        if "answer" not in code:
            raise ValueError(f"{problem_id}: formatted code has no answer symbol")

        config = dict(source["generation_config"])
        config["formatted_with_code_template"] = True
        submission = create_submission(
            problem_id=problem_id,
            generated_code=result.text,
            model=source["model"],
            generation_config=config,
            messages=[
                {"role": "assistant", "content": source["generated_code"]},
                {"role": "user", "content": parse_instruction},
                {"role": "assistant", "content": result.text},
            ],
        )
        submission.to_json(output_path)
        usage_path.write_text(
            json.dumps({"usage": result.usage, "attempts": result.attempts}, indent=2),
            encoding="utf-8",
        )
        print(f"[{challenge}/70] saved {output_path}", flush=True)
        return output_path

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        challenges = args.challenge or list(range(1, 71))
        futures = [executor.submit(format_one, challenge) for challenge in challenges]
        for future in concurrent.futures.as_completed(futures):
            future.result()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
