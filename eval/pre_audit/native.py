"""Process-isolated adapters for the three released rule-based evaluators.

The benchmark implementations remain vendored in their original repository
locations.  This module is the only pre-audit pipeline code that knows those
locations or their runner-specific result shapes.
"""

from __future__ import annotations

import importlib.util
import multiprocessing
import os
from pathlib import Path
import signal
import sys
import time
from types import ModuleType
from typing import Any

from eval.datasets import ROOT


_MODULES: dict[str, ModuleType] = {}


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load native evaluator: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _native(benchmark: str) -> ModuleType:
    if benchmark not in _MODULES:
        relative = {
            "ugphysics": "benchmarks/ugphysics/auxiliary_judge_codex.py",
            "prism": "benchmarks/prism/scripts/run_codex_rounds.py",
            "phybench": "benchmarks/phybench/evaluate_codex.py",
        }[benchmark]
        _MODULES[benchmark] = _load_module(
            f"eval_pre_audit_{benchmark}_native", ROOT / relative
        )
    return _MODULES[benchmark]


def _grade_child(connection, benchmark: str, row: dict[str, Any], response: str,
                 timeout: float) -> None:
    os.setsid()
    if hasattr(os, "sched_getaffinity"):
        os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:4])
    try:
        if benchmark == "prism":
            # The fork inherits the repository's utils package. PRISM has its
            # own package with the same name; resolve it inside this child only.
            for name in list(sys.modules):
                if name == "utils" or name.startswith("utils."):
                    sys.modules.pop(name, None)
        runner = _native(benchmark)
        if benchmark == "ugphysics":
            judge = runner.Judger(strict_extract=True)
            result = {
                "correct": bool(judge.auto_judge(response, row["answers"], precision=1e-2)),
                "extracted_answer": judge.extract_ans(response),
                "reference_answer": row["answers"],
            }
        elif benchmark == "phybench":
            result = runner.score(row, {"final_answer": response})
            result["correct"] = result.pop("success")
        else:
            result = runner.grade_one(row, {"response": response}, timeout)
            result["correct"] = result.pop("final_answer_correct")
        connection.send({**result, "id": row["_eval_id"], "grading_error": None})
    except Exception as error:
        connection.send({
            "id": row.get("_eval_id"),
            "correct": False,
            "grading_error": f"{type(error).__name__}: {error}",
        })
    finally:
        connection.close()


def grade_one(benchmark: str, row: dict[str, Any], response: str,
              timeout: float) -> dict[str, Any]:
    """Run one native grade with a hard timeout and no pipeline state mutation."""

    started = time.monotonic()
    context = multiprocessing.get_context("fork")
    receiver, sender = context.Pipe(duplex=False)
    child = context.Process(
        target=_grade_child, args=(sender, benchmark, row, response, timeout)
    )
    child.start()
    sender.close()
    try:
        if receiver.poll(timeout + 5):
            result = receiver.recv()
        else:
            result = {
                "id": row.get("_eval_id"),
                "correct": False,
                "grading_error": f"Native grading timeout after {timeout:g}s",
            }
    finally:
        child.join(1)
        if child.is_alive():
            os.killpg(child.pid, signal.SIGKILL)
            child.join()
        receiver.close()
    return {**result, "grading_seconds": time.monotonic() - started}


def auxiliary_judge(row: dict[str, Any], response: str, model: str, timeout: float,
                    max_output_tokens: int, fable_model: str | None = None) -> dict[str, Any]:
    """Apply UGPhysics's released auxiliary prompt to an automatic-score failure."""

    runner = _native("ugphysics")
    prompt = runner.build_prompt(
        runner.JUDGE_PROMPT_PATH.read_text(), row, {"completion": response},
        runner.Judger(strict_extract=True),
    )
    if prompt is None:
        return {"correct": False, "judge_called": False,
                "reason": "student answer extraction error"}
    if model == "claude-fable-5":
        from utils.fable_backend import (
            make_fable_client, parse_fable_response, resolve_fable_model,
        )

        api_model = resolve_fable_model(fable_model)
        with make_fable_client(timeout) as client:
            with client.messages.stream(
                model=api_model, max_tokens=max_output_tokens,
                system=runner.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                thinking={"type": "adaptive"}, output_config={"effort": "high"},
            ) as stream:
                raw = stream.get_final_message().model_dump(mode="json")
        parsed = parse_fable_response(raw, api_model)
        if parsed["refused"]:
            raise ValueError("UGPhysics auxiliary judge refused")
        report = parsed["response"]
        result = {"usage": parsed["usage"], "actual_model": parsed["actual_model"],
                  "raw_response": raw}
    else:
        from utils.codex_cli import CodexLLM, validate_codex_result

        reply = CodexLLM(
            model=model, model_reasoning_effort="high", timeout=timeout,
            system_prompt=runner.SYSTEM_PROMPT, strict_no_tools=True,
            max_exec_retries=0, max_tool_retries=0,
        ).complete(prompt)
        validate_codex_result(reply)
        report = reply.text
        result = {"usage": reply.usage, "actual_model": None}
    return {**result, "correct": runner.parse_verdict(report), "judge_called": True,
            "report": report, "judge_model": model}
