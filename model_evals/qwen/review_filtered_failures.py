#!/usr/bin/env python3
"""Audit every native non-pass from a filtered Qwen benchmark run."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from utils.codex_cli import CodexLLM  # noqa: E402


VERDICTS = ("GRADER_FAILURE", "MODEL_FAILURE")
SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "reason": {"type": "string"},
        "equivalent_or_correct_answer": {"type": "string"},
    },
    "required": ["verdict", "reason", "equivalent_or_correct_answer"],
    "additionalProperties": False,
}
SYSTEM_PROMPT = """You are a skeptical senior physics answer adjudicator. The benchmark rows with known
benchmark defects have already been removed. Review this particular Qwen response independently; do not
transfer credit from any other model or any older audit response.

Return GRADER_FAILURE only when this Qwen response fully answers every requested part and is physically and
mathematically correct, but the released deterministic grader missed an equivalent expression, notation,
format, ordering, or otherwise valid answer. Return MODEL_FAILURE when the response has any substantive
error, omission, wrong convention, unjustified numerical result, or missing requested subpart. A plausible
derivation, partial credit, or a grader parsing failure is not enough to award full credit. Verify decisive
algebra, dimensions, signs, and requested quantities against the supplied reference solution. The two
verdicts are exhaustive for this task. Give a concrete, concise reason."""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def source_rows(benchmark: str) -> dict[str, dict[str, Any]]:
    if benchmark == "phybench":
        path = REPO_ROOT / "benchmarks" / "phybench" / "data" / "PHYBench-fullques_v1.json"
        return {
            str(item["id"]): {
                "problem_statement": item["content"],
                "reference_solution": item.get("solution", ""),
                "reference_answer": item["answer"],
            }
            for item in json.loads(path.read_text(encoding="utf-8"))
        }
    path = REPO_ROOT / "audit" / "all-responses" / benchmark / "responses.jsonl"
    return {str(item["problem_id"]): item for item in read_jsonl(path)}


def build_cases(artifact: Path, benchmark: str) -> list[dict[str, Any]]:
    source = source_rows(benchmark)
    generations = {str(item["id"]): item for item in read_jsonl(artifact / "generations.jsonl")}
    scores = {str(item["id"]): item for item in read_jsonl(artifact / "scores.jsonl")}
    cases = []
    for item_id in sorted(scores):
        score = scores[item_id]
        correct = bool(score.get("correct", score.get("success", False)))
        if correct:
            continue
        generation = generations[item_id]
        native_details = {
            key: value for key, value in score.items()
            if key not in {"matches", "created_at"}
        }
        if benchmark == "phybench":
            reasoning = generation.get("reasoning") or ""
            response = generation.get("content") or generation.get("final_answer") or ""
            model_response = f"REASONING:\n{reasoning}\n\nFINAL RESPONSE:\n{response}"
        else:
            model_response = generation["response"]
        cases.append({
            "id": item_id,
            "problem": source[item_id]["problem_statement"],
            "reference_solution": source[item_id]["reference_solution"],
            "reference_answer": source[item_id].get("reference_answer"),
            "model_response": model_response,
            "finish_reason": generation.get("finish_reason"),
            "native_details": native_details,
        })
    return cases


def prompt_for(case: dict[str, Any]) -> str:
    return f"""Benchmark: {case['benchmark']}
Problem ID: {case['id']}
Generation finish reason: {case['finish_reason']}
Native grading details: {json.dumps(case['native_details'], ensure_ascii=False)}

PROBLEM:
{case['problem']}

REFERENCE SOLUTION:
{case['reference_solution']}

REFERENCE ANSWER:
{case.get('reference_answer') or '(included in the reference solution)'}

THIS QWEN RESPONSE:
{case['model_response']}

Decide whether this exact response deserves full credit. For GRADER_FAILURE, put the decisive equivalent
answer in equivalent_or_correct_answer. For MODEL_FAILURE, state the correct result or missing requirement
there when concise, otherwise use an empty string."""


def review(case: dict[str, Any], model: str, effort: str,
           timeout: float, schema: Path) -> dict[str, Any]:
    result = CodexLLM(model=model, model_reasoning_effort=effort, timeout=timeout).complete(
        prompt_for(case), system_prompt=SYSTEM_PROMPT, output_schema=schema,
    )
    parsed = json.loads(result.text)
    if parsed["verdict"] not in VERDICTS:
        raise ValueError(parsed)
    return {
        "id": case["id"],
        **parsed,
        "review_usage": result.usage,
        "review_wrapper_attempts": result.attempts,
    }


def write_summary(artifact: Path, benchmark: str, cases: list[dict[str, Any]],
                  reviews: list[dict[str, Any]]) -> None:
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    model = manifest.get("config", {}).get("model", "Qwen")
    native_scores = read_jsonl(artifact / "scores.jsonl")
    counts = Counter(item["verdict"] for item in reviews)
    native_correct = sum(bool(item.get("correct", item.get("success", False)))
                         for item in native_scores)
    adjusted_correct = native_correct + counts["GRADER_FAILURE"]
    denominator = len(manifest["evaluated_ids"])
    benchmark_failure_count = manifest["excluded_benchmark_failure_count"]
    result = {
        "benchmark": benchmark,
        "model": model,
        "benchmark_failure_excluded": benchmark_failure_count,
        "evaluated_rows": denominator,
        "native_rule_based_correct": native_correct,
        "native_rule_based_accuracy": native_correct / denominator,
        "reviewed_native_nonpasses": len(cases),
        "grader_failures_credited": counts["GRADER_FAILURE"],
        "genuine_model_failures": counts["MODEL_FAILURE"],
        "adjusted_correct": adjusted_correct,
        "adjusted_accuracy": adjusted_correct / denominator,
        "grader_failure_ids": sorted(item["id"] for item in reviews
                                     if item["verdict"] == "GRADER_FAILURE"),
        "model_failure_ids": sorted(item["id"] for item in reviews
                                    if item["verdict"] == "MODEL_FAILURE"),
    }
    (artifact / "audit_summary.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    case_by_id = {item["id"]: item for item in cases}
    lines = [
        f"# {model} {benchmark} non-pass audit", "",
        f"- Known benchmark failures excluded before generation: {benchmark_failure_count}",
        f"- Native rule-based result: {native_correct}/{denominator} "
        f"({100*native_correct/denominator:.2f}%)",
        f"- Grader failures credited: {counts['GRADER_FAILURE']}",
        f"- Genuine model failures: {counts['MODEL_FAILURE']}",
        f"- Adjusted result: {adjusted_correct}/{denominator} "
        f"({100*adjusted_correct/denominator:.2f}%)", "",
        "## Row-by-row review", "",
    ]
    for index, item in enumerate(sorted(reviews, key=lambda value: value["id"]), 1):
        case = case_by_id[item["id"]]
        lines.extend([
            f"### {index}. {item['id']}", "",
            f"**Verdict:** {item['verdict']}", "", item["reason"], "",
            f"**Equivalent/correct answer:** `{item['equivalent_or_correct_answer']}`", "",
            f"**Qwen response:** {case['model_response']}", "",
        ])
    (artifact / "audit_report.md").write_text("\n".join(lines).rstrip() + "\n",
                                               encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark", choices=("phybench", "prism", "ugphysics"))
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args()
    cases = build_cases(args.artifact, args.benchmark)
    for case in cases:
        case["benchmark"] = args.benchmark
    output = args.artifact / "audit.jsonl"
    schema = args.artifact / "audit.schema.json"
    schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
    existing = {str(item["id"]): item for item in read_jsonl(output)}
    pending = [case for case in cases if case["id"] not in existing]
    lock = threading.Lock()
    print(f"{args.benchmark}: reviewing {len(pending)} of {len(cases)} native non-passes",
          flush=True)
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {
            pool.submit(review, case, args.model, args.reasoning_effort,
                        args.timeout, schema): case["id"]
            for case in pending
        }
        for completed, future in enumerate(as_completed(futures), 1):
            item = future.result()
            existing[item["id"]] = item
            with lock, output.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
                handle.flush()
            print(f"{completed}/{len(pending)} {item['id']}: {item['verdict']}", flush=True)
    reviews = [existing[case["id"]] for case in cases]
    write_summary(args.artifact, args.benchmark, cases, reviews)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
