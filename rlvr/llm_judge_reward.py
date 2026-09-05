"""High-throughput PRISM reward backed by an external OpenAI-compatible vLLM server."""

from __future__ import annotations

import json
import math
import os
import random
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from llm_judge.prompts import get_prompt


PRISM_SOURCE = "physics/prism"
UGPHYSICS_SOURCE = "physics/ugphysics"
PROMPT_PATH = Path(__file__).with_name("llm_judge_prompt.txt")
RUBRIC_SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8").strip()
BINARY_PROMPT = get_prompt("default")
RUBRIC_SCORE_SCHEMA = {
    "name": "physics_judge_reward",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "candidate_conclusion": {"type": "string", "maxLength": 240},
            "reference_conclusion": {"type": "string", "maxLength": 240},
            "completion": {"type": "string", "enum": ["complete", "partial", "absent"]},
            "error_severity": {"type": "string", "enum": ["none", "minor", "major"]},
            "score_probabilities": {
                "type": "array",
                "items": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "minItems": 5,
                "maxItems": 5,
            },
            "critique": {"type": "string", "maxLength": 200},
        },
        "required": [
            "candidate_conclusion",
            "reference_conclusion",
            "completion",
            "error_severity",
            "score_probabilities",
            "critique",
        ],
        "additionalProperties": False,
    },
}
BINARY_SCORE_SCHEMA = {
    "name": "physics_judgment",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "grade": {"type": "integer", "enum": [0, 1]},
            "reason": {"type": "string", "minLength": 1, "maxLength": 1000},
        },
        "required": ["grade", "reason"],
        "additionalProperties": False,
    },
}


def _ground_truth_object(ground_truth: Any) -> dict[str, Any]:
    if isinstance(ground_truth, dict):
        return ground_truth
    if isinstance(ground_truth, str):
        value = json.loads(ground_truth)
        if isinstance(value, dict):
            return value
    raise ValueError("ground_truth must be a JSON object or encoded JSON object")


def _problem_and_reference(truth: dict[str, Any]) -> tuple[str, str]:
    problem = truth.get("problem")
    reference = truth.get("reference_answer")
    if not isinstance(problem, str) or not problem.strip():
        raise ValueError("ground truth is missing the full problem")
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("ground truth is missing the reference answer")
    return problem, reference


def _rubric_candidate_payload(solution: str, truth: dict[str, Any]) -> str:
    problem, reference = _problem_and_reference(truth)
    return (
        "<problem>\n"
        f"{problem}\n"
        "</problem>\n\n"
        "<reference>\n"
        f"{reference}\n"
        "</reference>\n\n"
        "<candidate>\n"
        f"{solution}\n"
        "</candidate>"
    )


def _binary_candidate_payload(solution: str, truth: dict[str, Any]) -> str:
    problem, reference = _problem_and_reference(truth)
    _system, user = BINARY_PROMPT.render(
        {
            "problem_statement": problem,
            "reference_solution": reference,
            "model_response": solution,
        }
    )
    return user


def _endpoint() -> str:
    base_url = os.environ.get("LLM_JUDGE_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
    return f"{base_url}/chat/completions"


def _request_body(solution: str, truth: dict[str, Any], *, binary: bool = False) -> bytes:
    model = os.environ.get("LLM_JUDGE_MODEL", "Qwen/Qwen3.5-27B")
    system_prompt = BINARY_PROMPT.system if binary else RUBRIC_SYSTEM_PROMPT
    user_prompt = (
        _binary_candidate_payload(solution, truth)
        if binary
        else _rubric_candidate_payload(solution, truth)
    )
    score_schema = BINARY_SCORE_SCHEMA if binary else RUBRIC_SCORE_SCHEMA
    if binary:
        # Match the validated Qwen3.5 judge configuration in llm_judge exactly.
        max_tokens = max(64, int(os.environ.get("LLM_JUDGE_BINARY_MAX_TOKENS", "8192")))
        sampling = {
            "temperature": float(os.environ.get("LLM_JUDGE_BINARY_TEMPERATURE", "0.6")),
            "top_p": float(os.environ.get("LLM_JUDGE_BINARY_TOP_P", "0.95")),
            "chat_template_kwargs": {"enable_thinking": True},
            "thinking_token_budget": int(
                os.environ.get("LLM_JUDGE_BINARY_THINKING_TOKEN_BUDGET", "4096")
            ),
            "top_k": int(os.environ.get("LLM_JUDGE_BINARY_TOP_K", "20")),
            "min_p": float(os.environ.get("LLM_JUDGE_BINARY_MIN_P", "0.0")),
        }
    else:
        max_tokens = max(64, int(os.environ.get("LLM_JUDGE_MAX_TOKENS", "384")))
        sampling = {
            "temperature": 0.0,
            "chat_template_kwargs": {"enable_thinking": False},
        }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "response_format": {"type": "json_schema", "json_schema": score_schema},
        **sampling,
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _post_json(body: bytes, timeout_seconds: float) -> dict[str, Any]:
    attempts = max(1, int(os.environ.get("LLM_JUDGE_RETRIES", "3")))
    request = urllib.request.Request(
        _endpoint(),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                value = json.loads(response.read().decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("judge response is not a JSON object")
            return value
        except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError):
            if attempt + 1 == attempts:
                raise
            # Short jittered backoff prevents synchronized retry storms while
            # keeping a reward step responsive.
            time.sleep((0.25 * (2**attempt)) + random.random() * 0.1)
    raise AssertionError("unreachable")


def _content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("judge response has no choices")
    message = choices[0].get("message", {})
    value = message.get("content")
    if not isinstance(value, str):
        raise ValueError("judge response has no message content")
    # Structured decoding should make this unnecessary, but retaining a narrow
    # fence fallback makes the client portable to older OpenAI-compatible servers.
    match = re.fullmatch(r"\s*```(?:json)?\s*(.*?)\s*```\s*", value, flags=re.DOTALL)
    return match.group(1) if match else value


def _score_rubric_response(response: dict[str, Any]) -> dict[str, float]:
    verdict = json.loads(_content(response))
    probabilities = verdict.get("score_probabilities")
    if not isinstance(probabilities, list) or len(probabilities) != 5:
        raise ValueError("judge must return five score probabilities")
    probabilities = [float(value) for value in probabilities]
    if any(not math.isfinite(value) or value < 0 for value in probabilities):
        raise ValueError("judge probabilities must be finite and nonnegative")
    total = sum(probabilities)
    if total <= 0:
        raise ValueError("judge probabilities sum to zero")
    probabilities = [value / total for value in probabilities]

    completion = verdict.get("completion")
    severity = verdict.get("error_severity")
    if completion not in {"complete", "partial", "absent"}:
        raise ValueError("judge returned an invalid completion label")
    if severity not in {"none", "minor", "major"}:
        raise ValueError("judge returned an invalid error severity")

    # Make the structured self-checks binding. This prevents a contradictory
    # probability vector from rewarding a response the judge itself calls
    # incomplete or materially wrong.
    max_level = 4
    if completion == "absent":
        max_level = min(max_level, 1)
    elif completion == "partial":
        max_level = min(max_level, 2)
    if severity == "major":
        max_level = min(max_level, 2)
    elif severity == "minor":
        max_level = min(max_level, 3)
    allowed_total = sum(probabilities[: max_level + 1])
    if allowed_total <= 0:
        probabilities = [float(level == max_level) for level in range(5)]
    else:
        probabilities = [
            probability / allowed_total if level <= max_level else 0.0
            for level, probability in enumerate(probabilities)
        ]
    expected_score = sum(level * probability for level, probability in enumerate(probabilities)) / 4.0
    return {
        "score": float(expected_score),
        "rubric_soft_pass_probability": float(probabilities[3] + probabilities[4]),
        "rubric_full_probability": float(probabilities[4]),
        "rubric_expected_level": float(expected_score * 4.0),
        "rubric_complete": float(completion == "complete"),
        "rubric_major_error": float(severity == "major"),
        "judge_error": 0.0,
    }


def _score_binary_response(response: dict[str, Any]) -> dict[str, float]:
    content = _content(response)
    try:
        verdict = json.loads(content)
    except json.JSONDecodeError:
        # Some vLLM structured generations contain an unescaped control
        # character in the free-text reason even though the constrained binary
        # grade itself is valid. Preserve that grade for evaluation.
        match = re.search(r'"grade"\s*:\s*([01])(?:\s*[,}])', content)
        if not match:
            raise
        return {"score": float(match.group(1)), "acc": float(match.group(1)), "judge_error": 0.0}
    grade = verdict.get("grade")
    reason = verdict.get("reason")
    if type(grade) is not int or grade not in (0, 1):
        raise ValueError("judge grade must be integer 0 or 1")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("judge reason must be a nonempty string")
    return {"score": float(grade), "acc": float(grade), "judge_error": 0.0}


def _failure(*, binary: bool) -> dict[str, float]:
    if binary:
        return {"score": 0.0, "acc": 0.0, "judge_error": 1.0}
    return {
        "score": 0.0,
        "rubric_soft_pass_probability": 0.0,
        "rubric_full_probability": 0.0,
        "rubric_expected_level": 0.0,
        "rubric_complete": 0.0,
        "rubric_major_error": 0.0,
        "judge_error": 1.0,
    }


def compute_score(
    data_source: str,
    solution_str: str,
    ground_truth: Any,
    extra_info: dict[str, Any] | None = None,
    timeout_seconds: float = 120.0,
) -> dict[str, float]:
    """Return dense rubric reward for training and a binary grade for validation.

    verl invokes many copies of this synchronous function in Ray reward actors.
    Their concurrent requests are continuously batched across the vLLM DP replicas.
    """
    binary = isinstance(extra_info, dict) and extra_info.get("split") == "validation"
    try:
        if data_source == UGPHYSICS_SOURCE and not binary:
            raise ValueError("UGPhysics is supported only as binary validation data")
        if data_source not in {PRISM_SOURCE, UGPHYSICS_SOURCE}:
            raise ValueError(f"unsupported LLM-judge data source: {data_source!r}")
        truth = _ground_truth_object(ground_truth)
        body = _request_body(solution_str, truth, binary=binary)
        parse_attempts = max(1, int(os.environ.get("LLM_JUDGE_PARSE_RETRIES", "2")))
        for attempt in range(parse_attempts):
            response = _post_json(body, timeout_seconds)
            try:
                if binary:
                    return _score_binary_response(response)
                return _score_rubric_response(response)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                if attempt + 1 == parse_attempts:
                    raise
                # Structured decoding enforces shape but cannot express a
                # positive probability sum. Regenerate rare semantic failures.
                continue
        raise AssertionError("unreachable")
    except Exception as exc:
        print(f"[llm-judge-reward] {type(exc).__name__}: {exc}", flush=True)
        if os.environ.get("LLM_JUDGE_RAISE_ERRORS") == "1":
            raise
        return _failure(binary=binary)
