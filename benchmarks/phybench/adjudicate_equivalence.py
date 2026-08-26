#!/usr/bin/env python3
"""Adversarially verify suspected native-EED false negatives."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1]))
from utils.codex_cli import CodexLLM  # noqa: E402


SYSTEM = """Act as a skeptical senior physics grader reviewing a claimed false negative from a symbolic
grader. The first reviewer claimed that at least one candidate answer is equivalent to the official
answer. Try actively to disprove that claim. Check the official derivation, signs, definitions, coordinate
conventions, dimensions, domains, omitted branches, proportional versus exact equality, and whether the
candidate merely resembles the answer. Assess only final-answer equivalence, not derivation quality.
Confirm a false negative only when equivalence is clear. Explain concrete algebra, not intuition."""

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["CONFIRMED_FALSE_NEGATIVE", "GRADER_CORRECT", "UNCERTAIN"],
        },
        "equivalent_candidate_ids": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "equivalent_candidate_ids", "reason"],
    "additionalProperties": False,
}


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def adjudicate(item: dict, source: dict, model: str, effort: str, timeout: float, schema: Path) -> dict:
    candidates = "\n\n".join(
        f"{candidate['candidate_id']} (EED {candidate['eed_score']}):\n{candidate['final_answer']}"
        for candidate in item["candidates"]
    )
    first_review = "\n".join(
        f"{review['candidate_id']}: {review['verdict']} — {review['reason']}"
        for review in item["candidate_reviews"]
    )
    prompt = f"""Problem ID: {item['id']}

PROBLEM:
{source['content']}

OFFICIAL ANSWER:
{source['answer']}

OFFICIAL SOLUTION:
{source['solution']}

CANDIDATES:
{candidates}

FIRST REVIEW (challenge this conclusion):
{first_review}

Return CONFIRMED_FALSE_NEGATIVE only if one or more candidates really are equivalent. List exactly those
candidate IDs. If none are equivalent, return GRADER_CORRECT and an empty list. Use UNCERTAIN if the
official material does not settle the issue."""
    result = CodexLLM(model=model, model_reasoning_effort=effort, timeout=timeout).complete(
        prompt, system_prompt=SYSTEM, output_schema=schema
    )
    parsed = json.loads(result.text)
    valid_ids = {candidate["candidate_id"] for candidate in item["candidates"]}
    if not set(parsed["equivalent_candidate_ids"]) <= valid_ids:
        raise ValueError(f"Unknown candidate ID for {item['id']}")
    if parsed["verdict"] == "GRADER_CORRECT" and parsed["equivalent_candidate_ids"]:
        raise ValueError(f"Inconsistent verdict for {item['id']}")
    return {
        "id": item["id"],
        **parsed,
        "review_usage": result.usage,
        "review_wrapper_attempts": result.attempts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    artifact = ROOT / "artifacts" / "gpt-5.6-sol-high-best-of-5"
    parser.add_argument("--review", type=Path, default=artifact / "equivalence_review.jsonl")
    parser.add_argument("--output", type=Path, default=artifact / "equivalence_adjudication.jsonl")
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args()
    reviews = [
        item for item in read_jsonl(args.review)
        if item["overall_assessment"] == "GRADER_FALSE_NEGATIVE"
    ]
    source = {
        str(item["id"]): item
        for item in json.loads((ROOT / "data" / "PHYBench-fullques_v1.json").read_text())
    }
    schema = args.output.with_suffix(".schema.json")
    schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
    existing = {item["id"] for item in read_jsonl(args.output)}
    pending = [item for item in reviews if item["id"] not in existing]
    lock = threading.Lock()
    print(f"adjudicating {len(pending)} of {len(reviews)} suspected false negatives", flush=True)
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {
            pool.submit(
                adjudicate, item, source[item["id"]], args.model,
                args.reasoning_effort, args.timeout, schema,
            ): item["id"]
            for item in pending
        }
        for future in as_completed(futures):
            result = future.result()
            with lock, args.output.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                handle.flush()
            print(f"adjudicated {result['id']}: {result['verdict']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
