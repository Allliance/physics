"""PRISM's rule reward for training and the binary LLM judge for validation."""

from __future__ import annotations

from typing import Any

from rlvr import llm_judge_reward, reward


def compute_score(
    data_source: str,
    solution_str: str,
    ground_truth: Any,
    extra_info: dict[str, Any] | None = None,
    timeout_seconds: float = 120.0,
) -> dict[str, float]:
    if isinstance(extra_info, dict) and extra_info.get("split") == "validation":
        return llm_judge_reward.compute_score(
            data_source,
            solution_str,
            ground_truth,
            extra_info=extra_info,
            timeout_seconds=timeout_seconds,
        )
    if data_source != reward.PRISM_SOURCE:
        raise ValueError(f"rule-based training requires PRISM, got {data_source!r}")
    return reward.compute_score(
        data_source,
        solution_str,
        ground_truth,
        extra_info=extra_info,
        timeout_seconds=timeout_seconds,
    )
