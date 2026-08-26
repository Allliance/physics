"""Judge HLE predictions through Codex CLI instead of the OpenAI API."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import sys
import tempfile
from pathlib import Path

import numpy as np
from datasets import load_dataset
from tqdm import tqdm

JUDGE_SYSTEM_PROMPT = """Answer using only the supplied prompt. Do not use tools, shell commands, files, web search, or external context.
Return only JSON matching the supplied output schema."""

JUDGE_PROMPT = """Judge whether the following [response] to [question] is correct or not based on the precise and unambiguous [correct_answer] below.

[question]: {question}

[response]: {response}

Extract the response's final exact answer. Use "None" if there is no exact final answer.

[correct_answer]: {correct_answer}

Explain only whether the extracted answer matches the supplied correct answer. Mark correct as "yes" only if they match, allowing a small margin of error for numerical answers; otherwise mark it "no". Extract the response's confidence from 0 to 100, or use 100 if none is present. Set strict to true."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "extracted_final_answer": {"type": "string"},
        "reasoning": {"type": "string"},
        "correct": {"type": "string", "enum": ["yes", "no"]},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "strict": {"type": "boolean", "const": True},
    },
    "required": [
        "extracted_final_answer",
        "reasoning",
        "correct",
        "confidence",
        "strict",
    ],
    "additionalProperties": False,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Judge HLE predictions with Codex CLI.")
    parser.add_argument("--dataset", default="cais/hle")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--judge", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--num-workers", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument(
        "--codex-cli-path",
        type=Path,
        default=Path("/shared/data/home/aa3242/physics/utils"),
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def calibration_error(confidence: np.ndarray, correct: np.ndarray, beta: int = 100) -> float:
    order = np.argsort(confidence)
    confidence = confidence[order]
    correct = correct[order]
    bins = [(start, min(start + beta, len(confidence))) for start in range(0, len(confidence), beta)]
    squared = 0.0
    for start, end in bins:
        difference = abs(float(np.mean(confidence[start:end])) - float(np.mean(correct[start:end])))
        squared += (end - start) / len(confidence) * difference**2
    return math.sqrt(squared)


def print_metrics(judged: dict, expected: int) -> None:
    complete = [value["judge_response"] for value in judged.values() if "judge_response" in value]
    correct = np.array([item["correct"] == "yes" for item in complete], dtype=float)
    confidence = np.array([item["confidence"] / 100 for item in complete])
    if len(complete) != expected:
        print(f"Available judgments: {len(complete)} | Expected: {expected}")
    accuracy = 100 * float(np.sum(correct)) / expected
    half_width = 1.96 * math.sqrt(accuracy * (100 - accuracy) / expected)
    print("*** Metrics ***")
    print(f"Accuracy: {accuracy:.2f}% +/- {half_width:.2f}% | n = {expected}")
    print(f"Calibration Error: {100 * calibration_error(confidence, correct):.1f}")


def main() -> int:
    args = parse_args()
    sys.path.insert(0, str(args.codex_cli_path.resolve()))
    from codex_cli import CodexLLM

    predictions = json.loads(args.predictions.read_text())
    dataset = load_dataset(args.dataset, split="test").select_columns(
        ["id", "question", "answer"]
    )
    questions = {row["id"]: row for row in dataset if row["id"] in predictions}
    if len(questions) != len(predictions):
        raise ValueError("Some prediction IDs were not found in the dataset")

    output = args.output or args.predictions.with_name(f"judged_{args.predictions.name}")
    judged = json.loads(output.read_text()) if output.exists() else {}
    pending = [question_id for question_id in predictions if question_id not in judged]
    print(f"Judging {len(predictions)} predictions; {len(pending)} pending; output={output}")

    client = CodexLLM(
        model=args.judge,
        model_reasoning_effort=args.reasoning_effort,
        timeout=args.timeout,
        system_prompt=JUDGE_SYSTEM_PROMPT,
        strict_no_tools=True,
        web_search="disabled",
        sandbox_mode="read-only",
        env_inherit="none",
    )

    with tempfile.TemporaryDirectory(prefix="hle-judge-") as tmp:
        schema_path = Path(tmp) / "judge-schema.json"
        schema_path.write_text(json.dumps(JUDGE_SCHEMA))

        def judge_one(question_id: str) -> tuple[str, dict] | None:
            question = questions[question_id]
            prediction = predictions[question_id]
            prompt = JUDGE_PROMPT.format(
                question=question["question"],
                correct_answer=question["answer"],
                response=prediction["response"],
            )
            try:
                result = client.complete(prompt, output_schema=schema_path)
                content = json.loads(result.text)
                item = dict(prediction)
                item["judge_response"] = {
                    "correct_answer": question["answer"],
                    "model_answer": content["extracted_final_answer"],
                    "reasoning": content["reasoning"],
                    "correct": content["correct"],
                    "confidence": content["confidence"],
                }
                item["judge_model"] = args.judge
                item["judge_reasoning_effort"] = args.reasoning_effort
                return question_id, item
            except Exception as exc:
                print(f"Error judging {question_id}: {exc}", file=sys.stderr)
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.num_workers) as pool:
            futures = [pool.submit(judge_one, question_id) for question_id in pending]
            for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures)):
                result = future.result()
                if result is None:
                    continue
                question_id, item = result
                judged[question_id] = item
                output.write_text(json.dumps(judged, indent=2))

    print_metrics(judged, len(predictions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
