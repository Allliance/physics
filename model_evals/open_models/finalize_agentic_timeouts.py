#!/usr/bin/env python3
"""Record missing agentic replacements as timed-out, incorrect attempts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval.storage import atomic_json, fingerprint
from model_evals.open_models.run_agentic_replacements import (
    DEFAULT_SOURCE,
    checkpoint_path,
    load_checkpoints,
    load_sources,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args()

    tasks, _ = load_sources(args.source)
    predictions = load_checkpoints(args.output, tasks, "predictions.json")
    judgments = load_checkpoints(args.output, tasks, "judgments.json")
    finalized = []
    dirty_keys = set()
    now = datetime.now(timezone.utc).isoformat()

    for task in tasks:
        key = (task["dataset"], task["attempt"])
        qid = task["id"]
        if qid in predictions[key]:
            existing = judgments[key].get(qid)
            if predictions[key][qid].get("timed_out") and existing and existing.get("timeout_failure"):
                existing["judgment"]["extracted_final_answer"] = "[NO RESPONSE: TIMEOUT]"
                dirty_keys.add(key)
            continue
        prediction = {
            "response": "",
            "usage": {
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "cache_write_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_output_tokens": 0,
            },
            "requested_model": "moonshotai/kimi-k3@preset/agentic-web",
            "actual_model": None,
            "attempts": 1,
            "tool_events": [],
            "refused": False,
            "timed_out": True,
            "timeout_seconds": args.timeout_seconds,
            "finalized_at": now,
            "replaces": {
                "dataset": task["dataset"],
                "attempt": task["attempt"],
                "id": qid,
                "original_prediction_sha256": task["original_prediction_sha256"],
                "original_judgment_sha256": task["original_judgment_sha256"],
            },
        }
        predictions[key][qid] = prediction
        judgments[key][qid] = {
            "judgment": {
                "extracted_final_answer": "[NO RESPONSE: TIMEOUT]",
                "reasoning": "The replacement agent timed out without returning a final answer.",
                "correct": "no",
                "confidence": 100,
                "strict": True,
            },
            "usage": {
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "cache_write_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_output_tokens": 0,
            },
            "raw_response": None,
            "requested_model": "gpt-5.6-sol",
            "actual_model": None,
            "judge_called": False,
            "timeout_failure": True,
            "prediction_sha256": fingerprint(prediction),
        }
        finalized.append(f"{task['dataset']}/attempt-{task['attempt']}/{qid}")
        dirty_keys.add(key)

    for task in tasks:
        key = (task["dataset"], task["attempt"])
        if key not in dirty_keys:
            continue
        atomic_json(checkpoint_path(args.output, task, "predictions.json"), predictions[key])
        atomic_json(checkpoint_path(args.output, task, "judgments.json"), judgments[key])

    print(f"finalized_timeouts={len(finalized)}")
    for item in finalized:
        print(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
