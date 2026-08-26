"""Run HLE predictions through Codex CLI instead of the OpenAI API."""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import mimetypes
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from datasets import load_dataset
from tqdm import tqdm


SYSTEM_PROMPT = """Answer using only the supplied prompt. Do not use tools, shell commands, files, web search, or external context.

Your response should be in the following format:
Explanation: {your explanation for your answer choice}
Answer: {your chosen answer}
Confidence: {your confidence score between 0% and 100% for your answer}"""

TOOLS_SYSTEM_PROMPT = """You may use the available tools, shell commands, scratch files, and web search to help answer the supplied question.

Your response should be in the following format:
Explanation: {your explanation for your answer choice}
Answer: {your chosen answer}
Confidence: {your confidence score between 0% and 100% for your answer}"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate HLE predictions with the codex_cli Python utility."
    )
    parser.add_argument("--dataset", default="cais/hle")
    parser.add_argument("--category", default="Physics")
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument(
        "--allow-tools",
        action="store_true",
        help="Allow Codex tool calls instead of rejecting and retrying them.",
    )
    parser.add_argument(
        "--web-search",
        default="disabled",
        choices=["disabled", "cached", "live"],
    )
    parser.add_argument(
        "--codex-cli-path",
        type=Path,
        default=Path("/shared/data/home/aa3242/physics/utils"),
        help="Directory containing the codex_cli package.",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--ids-file",
        type=Path,
        help="Optional JSON list of question IDs to evaluate.",
    )
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="Print available categories and exit without running Codex.",
    )
    return parser.parse_args()


def load_questions(dataset_name: str, category: str) -> tuple[list[dict], list[str]]:
    dataset = load_dataset(dataset_name, split="test")
    if "category" not in dataset.column_names:
        raise ValueError(
            f"Dataset has no 'category' column; columns: {dataset.column_names}"
        )
    # Avoid decoding the unused image_preview/rationale_image PIL columns.
    dataset = dataset.select_columns(["id", "question", "image", "category"])
    categories = sorted({str(value) for value in dataset["category"]})
    wanted = category.casefold()
    questions = [row for row in dataset if str(row["category"]).casefold() == wanted]
    return questions, categories


def materialize_image(value: str, directory: Path, question_id: str) -> Path | None:
    if not value:
        return None
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in question_id)
    if value.startswith("data:"):
        header, encoded = value.split(",", 1)
        mime = header[5:].split(";", 1)[0]
        suffix = mimetypes.guess_extension(mime) or ".img"
        path = directory / f"{safe_id}{suffix}"
        path.write_bytes(base64.b64decode(encoded))
        return path
    if value.startswith(("http://", "https://")):
        suffix = Path(urllib.parse.urlparse(value).path).suffix or ".img"
        path = directory / f"{safe_id}{suffix}"
        urllib.request.urlretrieve(value, path)
        return path
    path = Path(value)
    if path.exists():
        return path.resolve()
    raise ValueError(f"Unsupported image value for question {question_id}")


def main() -> int:
    args = parse_args()
    if args.num_workers < 1:
        raise ValueError("--num-workers must be at least 1")

    sys.path.insert(0, str(args.codex_cli_path.resolve()))
    from codex_cli import CodexLLM

    questions, categories = load_questions(args.dataset, args.category)
    if args.list_categories:
        print("\n".join(categories))
        return 0
    if not questions:
        raise ValueError(
            f"No rows matched category {args.category!r}. Available: {categories}"
        )
    if args.ids_file:
        requested_ids = set(json.loads(args.ids_file.read_text()))
        questions = [question for question in questions if question["id"] in requested_ids]
        found_ids = {question["id"] for question in questions}
        missing_ids = requested_ids - found_ids
        if missing_ids:
            raise ValueError(f"{len(missing_ids)} requested IDs were not found in the category")
    if args.max_samples is not None:
        questions = questions[: args.max_samples]

    output = args.output or Path(
        f"hle_{args.model}_{args.reasoning_effort}_{args.category.lower()}.json"
    )
    if output.exists():
        predictions = json.loads(output.read_text())
    else:
        predictions = {}
    pending = [q for q in questions if q["id"] not in predictions]
    print(
        f"Matched {len(questions)} {args.category!r} rows; "
        f"{len(pending)} pending; output={output}"
    )

    client = CodexLLM(
        model=args.model,
        model_reasoning_effort=args.reasoning_effort,
        timeout=args.timeout,
        system_prompt=TOOLS_SYSTEM_PROMPT if args.allow_tools else SYSTEM_PROMPT,
        strict_no_tools=not args.allow_tools,
        web_search=args.web_search,
        sandbox_mode="workspace-write" if args.allow_tools else "read-only",
        env_inherit="none",
    )

    def attempt(question: dict) -> tuple[str, dict] | None:
        try:
            with tempfile.TemporaryDirectory(prefix="hle-image-") as tmp:
                image = materialize_image(
                    question.get("image", ""), Path(tmp), question["id"]
                )
                result = client.complete(
                    question["question"], image_paths=[image] if image else None
                )
            return question["id"], {
                "model": args.model,
                "reasoning_effort": args.reasoning_effort,
                "category": question["category"],
                "response": result.text,
                "usage": result.usage,
                "attempts": result.attempts,
                "tool_events": [
                    event.get("item", {}).get("type")
                    for event in result.events
                    if event.get("item", {}).get("type")
                    in {"command_execution", "file_change", "mcp_tool_call", "web_search"}
                ],
            }
        except Exception as exc:
            print(f"Error on {question['id']}: {exc}", file=sys.stderr)
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.num_workers) as pool:
        futures = [pool.submit(attempt, question) for question in pending]
        for future in tqdm(
            concurrent.futures.as_completed(futures), total=len(futures)
        ):
            result = future.result()
            if result is None:
                continue
            question_id, prediction = result
            predictions[question_id] = prediction
            # Checkpoint every successful response so interrupted runs can resume.
            output.write_text(json.dumps(predictions, indent=2))

    print(f"Saved {len(predictions)} predictions to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
