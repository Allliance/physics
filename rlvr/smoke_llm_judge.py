"""Exercise the external judge concurrently before starting an RL run."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor

from rlvr.llm_judge_reward import PRISM_SOURCE, compute_score


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=16)
    args = parser.parse_args()
    truth = json.dumps(
        {
            "problem": "A particle has mass m and speed v. State its nonrelativistic kinetic energy.",
            "reference_answer": "The kinetic energy is K = (1/2) m v^2.",
        }
    )

    candidates = (
        ("correct", "The answer is K = m v^2 / 2."),
        ("wrong", "The answer is K = m v^2."),
        ("incomplete", "We should begin from the work-energy theorem, and then"),
    )

    def score(index: int, split: str) -> tuple[str, dict[str, float]]:
        label, candidate = candidates[index % len(candidates)]
        return label, compute_score(
            PRISM_SOURCE,
            candidate,
            truth,
            extra_info={"split": split},
        )

    results_by_mode = {}
    for mode, split in (("training_rubric", "train"), ("validation_binary", "validation")):
        with ThreadPoolExecutor(max_workers=args.requests) as executor:
            labeled_results = list(executor.map(lambda index: score(index, split), range(args.requests)))
        results = [result for _label, result in labeled_results]
        if any(result["judge_error"] for result in results):
            raise RuntimeError(f"external judge {mode} health check failed: {results}")
        results_by_mode[mode] = {
            label: [result for result_label, result in labeled_results if result_label == label]
            for label, _candidate in candidates
        }

    rubric = results_by_mode["training_rubric"]
    if min(result["score"] for result in rubric["correct"]) < 0.75:
        raise RuntimeError(f"rubric judge rejected correct controls: {rubric['correct']}")
    if max(result["score"] for result in rubric["wrong"]) > 0.5:
        raise RuntimeError(f"rubric judge accepted wrong controls: {rubric['wrong']}")
    if max(result["score"] for result in rubric["incomplete"]) > 0.5:
        raise RuntimeError(f"rubric judge accepted incomplete controls: {rubric['incomplete']}")

    binary = results_by_mode["validation_binary"]
    if any(result["score"] != 1.0 for result in binary["correct"]):
        raise RuntimeError(f"binary judge rejected correct controls: {binary['correct']}")
    for label in ("wrong", "incomplete"):
        if any(result["score"] != 0.0 for result in binary[label]):
            raise RuntimeError(f"binary judge accepted {label} controls: {binary[label]}")

    print(
        json.dumps(
            {"requests_per_mode": args.requests, "results": results_by_mode},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
