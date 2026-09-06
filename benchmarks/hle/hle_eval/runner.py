"""Evaluate GPT-5.6-Sol or Fable 5 on HLE with rounds, judging, and aggregation."""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import json
import mimetypes
import os
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from .backends import TOOL_PATH, make_predictor, resolve_fable_model
from .prompts import SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT
from .scoring import aggregate_scores, judge_backend_config, judge_round, load_answers

ARTIFACT_ROOT = Path(__file__).resolve().parents[1] / "artifacts"


def model_name(value: str) -> str:
    aliases = {"gpt-5.6-sol": "gpt-5.6-sol", "fable": "claude-fable-5",
               "fable-5": "claude-fable-5", "claude-fable-5": "claude-fable-5"}
    try:
        return aliases[value.casefold()]
    except KeyError:
        raise argparse.ArgumentTypeError("Choose gpt-5.6-sol or fable (Fable 5).") from None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="cais/hle")
    parser.add_argument("--category", default="Physics")
    parser.add_argument("--model", type=model_name, default="gpt-5.6-sol")
    parser.add_argument("--include-images", action=argparse.BooleanOptionalAction, default=False,
                        help="Include image questions as well as text-only questions (default: false).")
    parser.add_argument("--reasoning-effort", default="high",
                        choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--use-tools", "--allow-tools", dest="use_tools",
                        action=argparse.BooleanOptionalAction, default=False,
                        help="Enable computation and search tools (default: false).")
    parser.add_argument("--rounds", type=int, default=1, help="Independent attempts per question (default: 1).")
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
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ids-file", type=Path, help="JSON list of question IDs to evaluate.")
    parser.add_argument("--list-categories", action="store_true")
    args = parser.parse_args(argv)
    expected_judge = "claude-fable-5" if args.model == "gpt-5.6-sol" else "gpt-5.6-sol"
    if args.judge_model is not None and args.judge_model != expected_judge:
        parser.error(f"Cross-model judging requires --judge-model {expected_judge} for {args.model}.")
    args.judge_model = expected_judge
    if (args.num_workers < 1 or args.timeout <= 0 or
            (args.max_output_tokens is not None and args.max_output_tokens < 1)):
        parser.error("Workers, timeout, and output token budget must be positive.")
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
    if args.model == "gpt-5.6-sol" and (
        args.max_output_tokens is not None or args.reasoning_effort == "max"
    ):
        parser.error("--max-output-tokens and effort 'max' are Fable evaluation-only options.")
    if args.max_output_tokens is None:
        args.max_output_tokens = 32768
    return args


def load_questions(dataset_name: str, category: str) -> tuple[list[dict], list[str]]:
    from datasets import load_dataset

    dataset = load_dataset(dataset_name, split="test")
    # Do not decode unused image_preview/rationale_image columns or expose answers.
    dataset = dataset.select_columns(["id", "question", "image", "category"])
    categories = sorted({str(value) for value in dataset["category"]})
    return [row for row in dataset if str(row["category"]).casefold() == category.casefold()], categories


def select_questions(questions: list[dict], *, include_images: bool,
                     requested_ids: list[str] | None = None, max_samples: int | None = None,
                     excluded_ids: list[str] | None = None) -> list[dict]:
    if requested_ids is not None:
        wanted = set(requested_ids)
        missing = wanted - {q["id"] for q in questions}
        if missing:
            raise ValueError(f"Requested IDs not found in the category: {sorted(missing)}")
        questions = [q for q in questions if q["id"] in wanted]
    excluded_set = set(excluded_ids or [])
    questions = [q for q in questions if q["id"] not in excluded_set]
    if requested_ids is not None:
        excluded = [q["id"] for q in questions if q.get("image") and not include_images]
        if excluded:
            raise ValueError(f"Requested image questions require --include-images: {excluded}")
    if not include_images:
        questions = [q for q in questions if not q.get("image")]
    return questions if max_samples is None else questions[:max_samples]


def materialize_image(value: str, directory: Path, question_id: str) -> Path | None:
    if not value:
        return None
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in question_id)
    if value.startswith("data:"):
        header, encoded = value.split(",", 1)
        mime = header[5:].split(";", 1)[0]
        path = directory / f"{safe_id}{mimetypes.guess_extension(mime) or '.img'}"
        path.write_bytes(base64.b64decode(encoded, validate=True))
        return path
    if value.startswith(("http://", "https://")):
        suffix = Path(urllib.parse.urlparse(value).path).suffix or ".img"
        path = directory / f"{safe_id}{suffix}"
        with urllib.request.urlopen(value, timeout=60) as response:
            path.write_bytes(response.read())
        return path
    path = Path(value)
    if path.is_file():
        return path.resolve()
    raise ValueError(f"Unsupported image value for question {question_id}")


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
    print(f"Selected {len(questions)} {args.category!r} rows "
          f"({sum(bool(q.get('image')) for q in questions)} with images); "
          f"{len(pending)} pending; model={args.model}; output={output}", flush=True)
    if not pending:
        return predictions
    predict = make_predictor(args, manifest["api_model"])

    def attempt(question: dict) -> tuple[str, dict]:
        with tempfile.TemporaryDirectory(prefix="hle-image-") as tmp:
            image = materialize_image(question.get("image", ""), Path(tmp), question["id"])
            result = predict(question, image)
        return question["id"], {"model": args.model, "backend": manifest["backend"],
                                "reasoning_effort": args.reasoning_effort, "category": question["category"],
                                "has_image": bool(question.get("image")), **result}

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



def read_ids(path: Path | None, option: str) -> list[str] | None:
    if path is None:
        return None
    value = json.loads(path.read_text())
    if not isinstance(value, list) or not all(isinstance(qid, str) for qid in value):
        raise ValueError(f"{option} must contain a JSON list of strings.")
    return value


def round_path(output: Path, index: int) -> Path:
    return output if index == 1 else output.with_name(f"{output.stem}.round{index}{output.suffix}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    questions, categories = load_questions(args.dataset, args.category)
    if args.list_categories:
        print("\n".join(categories))
        return 0
    matched = len(questions)
    requested = read_ids(args.ids_file, "--ids-file")
    excluded = read_ids(args.exclude_ids_file, "--exclude-ids-file") or []
    questions = select_questions(questions, include_images=args.include_images,
                                 requested_ids=requested, excluded_ids=excluded,
                                 max_samples=args.max_samples)
    if not questions:
        raise ValueError(f"No questions selected. Available categories: {categories}")
    api_model = resolve_fable_model(args.fable_model) if args.model == "claude-fable-5" else None
    backend = "codex" if api_model is None else ("claude-cli" if args.use_tools else "anthropic")
    modality = "with_images" if args.include_images else "text_only"
    category = "".join(c if c.isalnum() or c in "-_" else "_" for c in args.category.lower())
    tools_suffix = "_tools" if args.use_tools else ""
    output = args.output or ARTIFACT_ROOT / f"hle_{args.model}_{args.reasoning_effort}_{category}_{modality}{tools_suffix}.json"
    manifest = {
        "version": 2, "dataset": args.dataset, "category": args.category.casefold(),
        "model": args.model, "backend": backend, "api_model": api_model,
        "reasoning_effort": args.reasoning_effort, "include_images": args.include_images,
        "use_tools": args.use_tools, "web_search": args.web_search,
        "max_tool_turns": args.max_tool_turns if api_model and args.use_tools else None,
        "max_output_tokens": args.max_output_tokens if api_model else None,
        "base_url": os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com") if api_model else None,
        "excluded_ids": sorted(set(excluded)), "question_ids": [q["id"] for q in questions],
        "questions_sha256": hashlib.sha256(json.dumps(questions, sort_keys=True).encode()).hexdigest(),
        "prompt_sha256": hashlib.sha256((TOOLS_SYSTEM_PROMPT if args.use_tools else SYSTEM_PROMPT).encode()).hexdigest(),
        "judge_model": args.judge_model, "judge_reasoning_effort": args.judge_reasoning_effort,
    }
    manifest.update(judge_backend_config(args))
    if args.use_tools and backend == "codex":
        manifest["tool_environment"] = {"PATH": TOOL_PATH}
    run_config = output.with_suffix(".run.json")
    if run_config.exists() and json.loads(run_config.read_text()) != manifest:
        raise ValueError("Run settings or selected questions changed; choose a new --output file.")
    write_json(run_config, manifest)
    print(f"Matched {matched} {args.category!r} rows; evaluating {len(questions)} questions "
          f"for {args.rounds} round(s); tools={args.use_tools}; aggregation={args.aggregation}", flush=True)
    # Keep references in the judge path only; prediction backends never receive them.
    answers = load_answers(args.dataset, manifest["question_ids"])
    judged_rounds = [{} for _ in range(args.rounds)]
    summary_path = output.with_suffix(".summary.json")

    def save_summary():
        summary = aggregate_scores(manifest["question_ids"], judged_rounds, args.aggregation)
        summary.update({"model": args.model, "use_tools": args.use_tools,
                        "include_images": args.include_images, "excluded_ids": sorted(set(excluded)),
                        "judge_model": args.judge_model,
                        "prediction_files": [str(round_path(output, r)) for r in range(1, args.rounds + 1)]})
        write_json(summary_path, summary)
        return summary

    # Invalidate any old final score before starting additional/missing rounds.
    save_summary()
    for index in range(1, args.rounds + 1):
        path = round_path(output, index)
        print(f"Round {index}/{args.rounds}", flush=True)
        predictions = run_generation_round(args, questions, path, {**manifest, "round": index})
        judged_path = path.with_name(f"{path.stem}.judged{path.suffix}")
        judged_rounds[index - 1] = judge_round(args, questions, answers, predictions, judged_path, write_json)
        summary = save_summary()
    if summary["complete"]:
        print(f"Final {args.aggregation} score: {summary['final_score_percent']:.2f}% "
              f"({len(questions)} questions, {args.rounds} rounds); summary={summary_path}", flush=True)
        return 0
    print(f"Evaluation incomplete: {summary['missing_judgments']} missing judgments; "
          "rerun the same command to resume. No final score was assigned.", flush=True)
    return 1
