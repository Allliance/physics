#!/usr/bin/env python3
"""Run the two-stage CritPt pipeline against an OpenAI-compatible vLLM server."""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from critpt.data_loader import JsonDataLoader
from critpt.generation.prompts import PromptBuilder, build_system_prompt
from critpt.submission import create_submission
from critpt.templates import ParsePrompt


def request_chat(url: str, payload: dict, timeout: float, attempts: int = 3) -> dict:
    body = json.dumps(payload).encode()
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(
                f"{url.rstrip('/')}/chat/completions",
                data=body,
                headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.load(response)
            result["_attempts"] = attempt
            return result
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == attempts:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def response_text(result: dict, include_reasoning: bool) -> str:
    message = result["choices"][0]["message"]
    content = message.get("content") or ""
    reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
    return f"{reasoning}\n\n{content}".strip() if include_reasoning else content.strip()


def code_from_response(text: str) -> str:
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    code = (blocks[-1] if blocks else text).strip()
    # Preserve useful code from an otherwise valid response whose closing fence
    # was omitted (commonly because the server reached max_tokens).
    code = re.sub(r"^```(?:python)?\s*", "", code, flags=re.IGNORECASE)
    code = re.sub(r"\s*```$", "", code)
    return code.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", default="Qwen/Qwen3.5-27B")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--format-max-tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.6)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--min-p", type=float, default=0.0)
    parser.add_argument("--presence-penalty", type=float, default=0.0)
    parser.add_argument("--repetition-penalty", type=float, default=1.0)
    parser.add_argument("--run-name", default="thinking_t0.6")
    parser.add_argument("--profile", choices=("qwen", "gpt-oss"), default="qwen")
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high"), default="high")
    parser.add_argument("--limit", type=int, default=70)
    parser.add_argument("--challenges", help="Comma-separated challenge numbers (overrides --limit)")
    parser.add_argument("--output-root", type=Path, default=ROOT / "results" / "vllm")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--stage", choices=("all", "solve", "format"), default="all")
    parser.add_argument("--format-source-chars", type=int, default=0,
                        help="Use only this many trailing characters of the first-stage response when formatting")
    parser.add_argument("--format-extra-instruction", default="")
    args = parser.parse_args()

    slug = args.model.replace("/", "_")
    reasoning_dir = args.output_root / slug / args.run_name / "0"
    formatted_dir = args.output_root.parent / "vllm_formatted" / slug / args.run_name / "0"
    reasoning_dir.mkdir(parents=True, exist_ok=True)
    formatted_dir.mkdir(parents=True, exist_ok=True)
    # This backend exposes no agent tool loop. Advertising shell/web tools makes
    # Qwen emit pseudo tool calls indefinitely instead of completing an answer.
    system_prompt = build_system_prompt(False, False, False)

    def solve(challenge: int) -> Path:
        loader = JsonDataLoader(ROOT / "data/public_test_challenges/json" / f"Challenge_{challenge}.json")
        problem = loader.load_main_problem()
        path = reasoning_dir / f"{problem.problem_id}.json"
        if path.exists() and not args.overwrite:
            print(f"[solve {challenge}/70] skip", flush=True)
            return path
        prompt = PromptBuilder(loader.get_reader(), False, False, False).main_step().prompt
        payload = {
            "model": args.model,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
            "max_tokens": args.max_tokens,
            "temperature": args.temperature,
            "top_p": args.top_p,
        }
        if args.profile == "gpt-oss":
            payload["reasoning_effort"] = args.reasoning_effort
        else:
            payload.update(top_k=args.top_k, min_p=args.min_p,
                           presence_penalty=args.presence_penalty,
                           repetition_penalty=args.repetition_penalty)
        print(f"[solve {challenge}/70] generating", flush=True)
        result = request_chat(args.base_url, payload, args.timeout)
        text = response_text(result, include_reasoning=True)
        if not text:
            raise ValueError(f"{problem.problem_id}: empty response")
        config = {"parsing": False, "use_python": False, "use_web_search": False,
                  "thinking": True, "temperature": args.temperature, "top_p": args.top_p,
                  "max_tokens": args.max_tokens, "backend": "vllm"}
        if args.profile == "gpt-oss":
            config["reasoning_effort"] = args.reasoning_effort
        else:
            config.update(top_k=args.top_k, min_p=args.min_p,
                          presence_penalty=args.presence_penalty,
                          repetition_penalty=args.repetition_penalty)
        create_submission(problem.problem_id, text, f"vllm/{args.model}", config,
                          payload["messages"] + [{"role": "assistant", "content": text}]).to_json(path)
        path.with_name(path.stem + ".usage.json").write_text(json.dumps({"usage": result.get("usage", {}), "attempts": result["_attempts"]}, indent=2))
        print(f"[solve {challenge}/70] saved", flush=True)
        return path

    def format_answer(challenge: int) -> Path:
        problem_id = f"Challenge_{challenge}_main"
        source_path = reasoning_dir / f"{problem_id}.json"
        output_path = formatted_dir / f"{problem_id}.json"
        if output_path.exists() and not args.overwrite:
            print(f"[format {challenge}/70] skip", flush=True)
            return output_path
        source = json.loads(source_path.read_text())
        loader = JsonDataLoader(ROOT / "data/public_test_challenges/json" / f"Challenge_{challenge}.json")
        instruction = ParsePrompt.default_system_prompt(code_template=loader.load_main_problem().code_template)
        source_text = source["generated_code"]
        if args.format_source_chars:
            source_text = source_text[-args.format_source_chars:]
        messages = [
            {"role": "system", "content": "Perform only the requested code-template formatting step. Return completed Python code only."},
            {"role": "assistant", "content": source_text},
            {"role": "user", "content": instruction + ("\n\n" + args.format_extra_instruction
                                                         if args.format_extra_instruction else "")},
        ]
        payload = {"model": args.model, "messages": messages, "max_tokens": args.format_max_tokens}
        if args.profile == "gpt-oss":
            payload.update(temperature=1.0, top_p=1.0, reasoning_effort="low")
        else:
            payload.update(temperature=0.0,
                           chat_template_kwargs={"enable_thinking": False})
        print(f"[format {challenge}/70] generating", flush=True)
        failures = []
        for semantic_attempt in range(1, 4):
            result = request_chat(args.base_url, payload, args.timeout)
            text = response_text(result, include_reasoning=False)
            code = code_from_response(text)
            try:
                tree = ast.parse(code)
                names = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
                assigned = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
                if "answer" not in names | assigned:
                    raise ValueError("missing answer symbol")
                break
            except (SyntaxError, ValueError) as exc:
                failures.append(f"attempt {semantic_attempt}: {exc}\n\n{text}")
        else:
            output_path.with_suffix(".failed.txt").write_text("\n\n===== RETRY =====\n\n".join(failures))
            raise ValueError(f"{problem_id}: formatter failed validation after 3 attempts")
        config = dict(source.get("generation_config") or {})
        config["formatted_with_code_template"] = True
        create_submission(problem_id, text, source["model"], config,
                          [{"role": "assistant", "content": source["generated_code"]},
                           {"role": "user", "content": instruction},
                           {"role": "assistant", "content": text}]).to_json(output_path)
        output_path.with_name(output_path.stem + ".usage.json").write_text(json.dumps({"usage": result.get("usage", {}), "attempts": result["_attempts"]}, indent=2))
        print(f"[format {challenge}/70] saved", flush=True)
        return output_path

    challenges = ([int(value) for value in args.challenges.split(",")]
                  if args.challenges else range(1, min(args.limit, 70) + 1))
    functions = {"all": (solve, format_answer), "solve": (solve,),
                 "format": (format_answer,)}[args.stage]
    for function in functions:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(function, challenge) for challenge in challenges]
            for future in concurrent.futures.as_completed(futures):
                future.result()
    print(formatted_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
