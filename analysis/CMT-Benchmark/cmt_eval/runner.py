"""Evaluate supported Codex, Gemini, or Fable models on CMT."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import tempfile
from pathlib import Path

from .backends import TOOL_PATH, make_predictor, resolve_fable_model
from .dataset import load_dataset, read_ids, select_questions
from .prompts import JUDGE_PROMPT, JUDGE_SCHEMA, JUDGE_SYSTEM_PROMPT, SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT
from .scoring import aggregate_scores, judge_backend_config, judge_round, fingerprint

BENCHMARK_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = BENCHMARK_ROOT / "artifacts"


def model_name(value: str) -> str:
    aliases = {"gemini": "gemini-3.1-pro-preview", "gemini-3.1-pro": "gemini-3.1-pro-preview",
               "gemini-3.1-pro-preview": "gemini-3.1-pro-preview", "gpt-5.6-sol": "gpt-5.6-sol",
               "luna": "gpt-5.6-luna", "gpt-5.6-luna": "gpt-5.6-luna",
               "astra": "gpt-6-astra", "gpt-6-astra": "gpt-6-astra",
               "gpt-oss-120b": "gpt-oss-120b", "gpt-oss": "gpt-oss-120b", "fable": "claude-fable-5",
               "kimi-k3": "kimi-k3", "kimi": "kimi-k3",
               "glm-5.3": "glm-5.3", "glm": "glm-5.3",
               "deepseek-v4-pro": "deepseek-v4-pro", "deepseek": "deepseek-v4-pro",
               "fable-5": "claude-fable-5", "claude-fable-5": "claude-fable-5"}
    try:
        return aliases[value.casefold()]
    except KeyError:
        raise argparse.ArgumentTypeError("Choose gpt-5.6-sol, gpt-5.6-luna, gpt-6-astra, gpt-oss-120b, kimi-k3, glm-5.3, deepseek-v4-pro, gemini-3.1-pro-preview, or fable (Fable 5).") from None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=BENCHMARK_ROOT / "data" / "cmt_data_clean.json")
    parser.add_argument("--category", default="all", help="CMT type to select (default: all).")
    parser.add_argument("--model", type=model_name, default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high",
                        choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--use-tools", "--allow-tools", dest="use_tools",
                        action=argparse.BooleanOptionalAction, default=False,
                        help="Enable computation and search tools (default: false).")
    parser.add_argument("--rounds", type=int, default=1, help="Independent attempts per question (default: 1).")
    parser.add_argument("--round-workers", type=int,
                        help="Rounds to overlap; defaults to 4 for multi-round GPT-OSS runs and 1 otherwise.")
    parser.add_argument("--aggregation", choices=["mean", "max"], default="mean",
                        help="Aggregate each question across rounds before averaging (default: mean).")
    parser.add_argument("--exclude-ids-file", "--exclude-ids", dest="exclude_ids_file", type=Path,
                        help="Optional JSON file containing a list of question IDs to exclude.")
    parser.add_argument("--web-search", choices=["disabled", "cached", "live"],
                        help="With tools, defaults to live; without tools, disabled.")
    parser.add_argument("--claude-bin", default="claude", help="Claude CLI for Fable tool-enabled runs.")
    parser.add_argument("--max-tool-turns", type=int, default=20, help="Fable tool-session turn limit.")
    parser.add_argument("--judge-model", type=model_name,
                        help="Automatically uses the other model: Fable judges Sol; Sol judges Fable.")
    parser.add_argument("--judge-reasoning-effort", default="high", choices=["low", "medium", "high", "xhigh"])
    parser.add_argument("--codex-cli-path", type=Path, default=Path(__file__).resolve().parents[3] / "utils")
    parser.add_argument("--fable-model", help="Fable 5 API/gateway model ID, for evaluation or judging.")
    parser.add_argument("--max-output-tokens", type=int,
                        help="Fable response token budget including reasoning (default: 32768).")
    parser.add_argument("--output", type=Path, help="JSON output inside artifacts/; relative paths use the benchmark directory.")
    parser.add_argument("--ids-file", type=Path, help="JSON list of question IDs to evaluate.")
    parser.add_argument("--list-categories", action="store_true")
    args = parser.parse_args(argv)
    if args.round_workers is None:
        args.round_workers = min(4, args.rounds) if args.model in {"gpt-oss-120b", "kimi-k3", "glm-5.3", "deepseek-v4-pro"} else 1
    expected_judge = "gpt-5.6-sol" if args.model in {"claude-fable-5", "kimi-k3", "glm-5.3", "deepseek-v4-pro"} else "claude-fable-5"
    if args.judge_model is not None and args.judge_model != expected_judge:
        parser.error(f"Cross-model judging requires --judge-model {expected_judge} for {args.model}.")
    args.judge_model = expected_judge
    if (args.num_workers < 1 or args.round_workers < 1 or args.timeout <= 0 or
            (args.max_output_tokens is not None and args.max_output_tokens < 1)):
        parser.error("Workers, round workers, timeout, and output token budget must be positive.")
    if args.max_samples is not None and args.max_samples < 1:
        parser.error("--max-samples must be positive.")
    if args.rounds < 1 or args.max_tool_turns < 1:
        parser.error("--rounds and --max-tool-turns must be positive.")
    if args.web_search is None:
        args.web_search = "live" if args.use_tools else "disabled"
    if not args.use_tools and args.web_search != "disabled":
        parser.error("--web-search requires --use-tools.")
    if args.model == "claude-fable-5" and args.web_search == "cached":
        parser.error("Fable supports live or disabled web search, not cached search.")
    if args.model in {"kimi-k3", "glm-5.3", "deepseek-v4-pro"} and args.use_tools:
        parser.error("Local open-model evaluation currently supports no-tools runs only.")
    if args.model in {"gpt-5.6-sol", "gpt-5.6-luna"} and (
        args.max_output_tokens is not None or args.reasoning_effort == "max"
    ):
        parser.error("--max-output-tokens and effort 'max' are Fable evaluation-only options.")
    if args.model == "gemini-3.1-pro-preview":
        if args.reasoning_effort not in {"low", "medium", "high", "max"}:
            parser.error("Gemini supports low, medium, high, or max (mapped to high).")
        if args.web_search == "cached":
            parser.error("Gemini supports live or disabled web search.")
    if args.max_output_tokens is None:
        args.max_output_tokens = 65536 if args.model in {"gemini-3.1-pro-preview", "kimi-k3", "glm-5.3", "deepseek-v4-pro"} else 32768
    return args


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name + ".", delete=False) as f:
        temporary = Path(f.name)
        json.dump(value, f, indent=2)
        f.write("\n")
    temporary.replace(path)


def load_checkpoint(output: Path, manifest: dict) -> dict:
    metadata = output.with_suffix(output.suffix + ".meta.json")
    if metadata.exists():
        if json.loads(metadata.read_text()) != manifest:
            raise ValueError("Run settings or selected questions changed; choose a new --output file.")
    elif output.exists():
        raise ValueError("Existing predictions have no run manifest; choose a new --output file.")
    predictions = json.loads(output.read_text()) if output.exists() else {}
    if not isinstance(predictions, dict) or set(predictions) - set(manifest["question_ids"]):
        raise ValueError("Checkpoint contains unexpected question IDs.")
    for value in predictions.values():
        if (value.get("model") != manifest["model"] or
                value.get("reasoning_effort") != manifest["reasoning_effort"] or not value.get("response")):
            raise ValueError("Checkpoint contains incompatible or empty predictions.")
    if not metadata.exists():
        write_json(metadata, manifest)
    return predictions


def run_generation_round(args, questions: list[dict], output: Path, manifest: dict) -> dict:
    predictions = load_checkpoint(output, manifest)
    pending = [q for q in questions if q["id"] not in predictions]
    print(f"Selected {len(questions)} {args.category!r} rows; "
          f"{len(pending)} pending; model={args.model}; output={output}", flush=True)
    if not pending:
        return predictions
    predict = make_predictor(args, manifest["api_model"])

    def attempt(question: dict) -> tuple[str, dict]:
        result = predict(question, None)
        if not isinstance(result.get("response"), str) or not result["response"].strip():
            raise ValueError("Model returned an empty response; rerun to retry.")
        return question["id"], {"model": args.model, "backend": manifest["backend"],
                                "reasoning_effort": args.reasoning_effort,
                                "category": question["category"], **result}

    failures = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.num_workers) as pool:
        futures = {pool.submit(attempt, q): q["id"] for q in pending}
        for future in concurrent.futures.as_completed(futures):
            try:
                question_id, prediction = future.result()
            except Exception as exc:
                failures += 1
                print(f"Error on {futures[future]}: {exc}", file=sys.stderr, flush=True)
                continue
            predictions[question_id] = prediction
            write_json(output, predictions)
            print(f"Saved {question_id} ({len(predictions)}/{len(questions)})", flush=True)
    print(f"Saved {len(predictions)} predictions; {failures} failed. Rerun the same command to retry failures.")
    return predictions



def round_path(output: Path, index: int) -> Path:
    return output if index == 1 else output.with_name(f"{output.stem}.round{index}{output.suffix}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.dataset = args.dataset.resolve()
    questions, answers = load_dataset(args.dataset)
    categories = sorted({q["category"] for q in questions})
    if args.list_categories:
        print("\n".join(categories))
        return 0
    matched = len(select_questions(questions, category=args.category))
    requested = read_ids(args.ids_file, "--ids-file")
    excluded = read_ids(args.exclude_ids_file, "--exclude-ids-file") or []
    questions = select_questions(questions, category=args.category,
                                 requested_ids=requested, excluded_ids=excluded,
                                 max_samples=args.max_samples)
    if not questions:
        raise ValueError(f"No questions selected. Available categories: {categories}")
    api_model = resolve_fable_model(args.fable_model) if args.model == "claude-fable-5" else None
    backend = "codex" if api_model is None else ("claude-cli" if args.use_tools else "anthropic")
    if args.model == "gemini-3.1-pro-preview":
        api_model, backend = args.model, "gemini"
    if args.model in {"gpt-oss-120b", "kimi-k3", "glm-5.3", "deepseek-v4-pro"}:
        backend = "codex-local-vllm" if args.use_tools else "openai-compatible"
    category = "".join(c if c.isalnum() or c in "-_" else "_" for c in args.category.lower())
    tools_suffix = "_tools" if args.use_tools else ""
    output = args.output or ARTIFACT_ROOT / f"cmt_{args.model}_{args.reasoning_effort}_{category}{tools_suffix}.json"
    if not output.is_absolute():
        output = BENCHMARK_ROOT / output
    output = output.resolve()
    if not output.is_relative_to(ARTIFACT_ROOT.resolve()) or output.suffix != ".json":
        raise ValueError("--output must be a .json file inside the benchmark artifacts/ directory.")
    answers = {q["id"]: answers[q["id"]] for q in questions}
    manifest = {
        "version": 1, "benchmark": "CMT", "dataset": str(args.dataset), "category": args.category.casefold(),
        "model": args.model, "backend": backend, "api_model": api_model,
        "reasoning_effort": args.reasoning_effort,
        "use_tools": args.use_tools, "web_search": args.web_search,
        "max_tool_turns": args.max_tool_turns if api_model and args.use_tools else None,
        "max_output_tokens": args.max_output_tokens if api_model or args.model in {"gpt-oss-120b", "kimi-k3", "glm-5.3", "deepseek-v4-pro"} else None,
        "base_url": os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com") if api_model else None,
        "excluded_ids": sorted(set(excluded)), "question_ids": [q["id"] for q in questions],
        "questions_sha256": fingerprint(questions),
        "answers_sha256": fingerprint(answers),
        "judge_prompt_sha256": fingerprint([JUDGE_PROMPT, JUDGE_SCHEMA, JUDGE_SYSTEM_PROMPT]),
        "prompt_sha256": fingerprint(TOOLS_SYSTEM_PROMPT if args.use_tools else SYSTEM_PROMPT),
        "judge_model": args.judge_model, "judge_reasoning_effort": args.judge_reasoning_effort,
    }
    manifest.update(judge_backend_config(args))
    if backend == "gemini":
        sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
        from utils.gemini_backend import backend_metadata
        manifest.update(backend_metadata(args.reasoning_effort))
        manifest["max_tool_turns"] = None
    if backend in {"openai-compatible", "codex-local-vllm"}:
        sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
        from utils.openai_compatible import backend_metadata
        manifest.update(backend_metadata())
    if backend == "codex-local-vllm":
        manifest["wire_api"] = "responses"
        manifest["tool_environment"] = {"PATH": TOOL_PATH, "harness": "codex exec"}
    if args.use_tools and backend == "codex":
        manifest["tool_environment"] = {"PATH": TOOL_PATH}
    run_config = output.with_suffix(".run.json")
    if run_config.exists() and json.loads(run_config.read_text()) != manifest:
        raise ValueError("Run settings or selected questions changed; choose a new --output file.")
    write_json(run_config, manifest)
    print(f"Matched {matched} {args.category!r} rows; evaluating {len(questions)} questions "
          f"for {args.rounds} round(s); tools={args.use_tools}; aggregation={args.aggregation}", flush=True)
    # Keep references in the judge path only; prediction backends never receive them.
    judged_rounds = [{} for _ in range(args.rounds)]
    summary_path = output.with_suffix(".summary.json")

    def save_summary():
        summary = aggregate_scores(manifest["question_ids"], judged_rounds, args.aggregation)
        summary.update({"model": args.model, "use_tools": args.use_tools,
                        "dataset": str(args.dataset), "excluded_ids": sorted(set(excluded)),
                        "judge_model": args.judge_model,
                        "prediction_files": [str(round_path(output, r)) for r in range(1, args.rounds + 1)]})
        write_json(summary_path, summary)
        return summary

    # Invalidate any old final score before starting additional/missing rounds.
    save_summary()
    active_rounds = min(args.round_workers, args.rounds, args.num_workers)
    round_args = argparse.Namespace(**vars(args))
    round_args.num_workers = args.num_workers // active_rounds

    def evaluate_round(index: int):
        path = round_path(output, index)
        print(f"Round {index}/{args.rounds}", flush=True)
        predictions = run_generation_round(round_args, questions, path, {**manifest, "round": index})
        judged_path = path.with_name(f"{path.stem}.judged{path.suffix}")
        return judge_round(round_args, questions, answers, predictions, judged_path, write_json)

    with concurrent.futures.ThreadPoolExecutor(max_workers=active_rounds) as pool:
        futures = {pool.submit(evaluate_round, index): index for index in range(1, args.rounds + 1)}
        for future in concurrent.futures.as_completed(futures):
            judged_rounds[futures[future] - 1] = future.result()
            summary = save_summary()
    if summary["complete"]:
        print(f"Final {args.aggregation} score: {summary['final_score_percent']:.2f}% "
              f"({len(questions)} questions, {args.rounds} rounds); summary={summary_path}", flush=True)
        return 0
    print(f"Evaluation incomplete: {summary['missing_judgments']} missing judgments; "
          "rerun the same command to resume. No final score was assigned.", flush=True)
    return 1
