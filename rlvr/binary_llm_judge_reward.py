"""Binary LLM-judge reward for both PRISM training and validation."""

from __future__ import annotations

from typing import Any

from rlvr import llm_judge_reward


def compute_score(
    data_source: str,
    solution_str: str,
    ground_truth: Any,
    extra_info: dict[str, Any] | None = None,
    timeout_seconds: float = 120.0,
) -> dict[str, float]:
    """Return the judge's holistic correctness grade as an exact 0/1 reward."""
    binary_info = dict(extra_info or {})
    binary_info["split"] = "validation"
    return llm_judge_reward.compute_score(
        data_source,
        solution_str,
        ground_truth,
        extra_info=binary_info,
        timeout_seconds=timeout_seconds,
    )
