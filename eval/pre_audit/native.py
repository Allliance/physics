"""Process-isolated adapters for the three released rule-based evaluators.

The benchmark implementations are pristine upstream Git submodules. Imports,
resource limits, response formatting, and transport adaptation live here.
"""

from __future__ import annotations

import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from types import ModuleType
from typing import Any

from eval.datasets import ROOT
from eval.storage import file_hash


_MODULES: dict[str, ModuleType] = {}
REPOSITORIES = {
    "phybench": "https://github.com/phybench-official/phybench.git",
    "prism": "https://github.com/Open-PRISM/PRISM-Physics-Code.git",
    "ugphysics": "https://github.com/YangLabHKUST/UGPhysics.git",
}
SOURCE_DIRS = {"phybench": "EED", "prism": "utils", "ugphysics": "codes"}
JUDGE_PROMPT_PATH = ROOT / "benchmarks/ugphysics/data/judge_prompt.txt"
SYSTEM_PROMPT = (
    "Act as the requested physics equivalence judge. Follow the supplied grading "
    "instructions exactly. Do not use tools, files, web search, or external context."
)
ANSWER_SCHEMA = {"type": "object", "properties": {"final_answer": {"type": "string"}},
                 "required": ["final_answer"], "additionalProperties": False}


def provenance(benchmark: str) -> dict[str, Any]:
    root = ROOT / "benchmarks" / benchmark
    source_dir = root / SOURCE_DIRS[benchmark]
    if not (root / ".git").exists() or not source_dir.is_dir():
        raise FileNotFoundError(
            f"{benchmark} upstream checkout is missing. Run: "
            f"git submodule update --init benchmarks/{benchmark}"
        )
    revision = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True,
    ).strip()
    sources = sorted(source_dir.glob("*.py"))
    if benchmark == "ugphysics":
        sources.append(JUDGE_PROMPT_PATH)
    return {"repository": REPOSITORIES[benchmark], "commit": revision,
            "sources_sha256": {str(path.relative_to(ROOT)): file_hash(path) for path in sources},
            "adapter_sha256": file_hash(Path(__file__)),
            "ugphysics_precision": 1e-2 if benchmark == "ugphysics" else None}


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
        root = ROOT / "benchmarks" / benchmark
        relative = {"ugphysics": "codes/judge.py", "prism": "utils/grade_utils.py",
                    "phybench": "EED/EED.py"}[benchmark]
        if not (root / relative).is_file():
            raise FileNotFoundError(
                f"Missing upstream scorer; run git submodule update --init benchmarks/{benchmark}"
            )
        # Both PRISM and UGPhysics own a top-level utils module. Resolve it only
        # in an isolated child, leaving the pipeline's package imports intact.
        for name in list(sys.modules):
            if name == "utils" or name.startswith("utils.") or name == "math_equivalence":
                sys.modules.pop(name, None)
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(root if benchmark == "prism" else root / SOURCE_DIRS[benchmark]))
        _MODULES[benchmark] = _load_module(
            f"eval_pre_audit_{benchmark}_native", root / relative
        )
    return _MODULES[benchmark]


def normalize_latex(value: str) -> str:
    """Preserve the former PHYBench presentation-only input normalization."""
    value = value.strip()
    for opening, closing in (("\\[", "\\]"), ("$$", "$$"), ("$", "$")):
        if value.startswith(opening) and value.endswith(closing):
            value = value[len(opening):len(value) - len(closing)].strip()
            break
    return value.replace("\\left", "").replace("\\right", "").strip()


def unwrap_presentation_macros(expr: str) -> str:
    """Keep the former PRISM boxed/fbox compatibility fix outside upstream."""
    for macro in (r"\boxed", r"\fbox"):
        search_from = 0
        while True:
            start = expr.find(macro, search_from)
            if start < 0:
                break
            brace = start + len(macro)
            while brace < len(expr) and expr[brace].isspace():
                brace += 1
            if brace >= len(expr) or expr[brace] != "{":
                search_from = brace
                continue
            depth = 0
            end = brace
            while end < len(expr):
                if expr[end] == "{":
                    depth += 1
                elif expr[end] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                end += 1
            if depth:
                search_from = brace + 1
                continue
            expr = expr[:start] + expr[brace + 1:end] + expr[end + 1:]
            search_from = start
    return expr


def _grading_standard(problem: dict[str, Any]) -> list[dict[str, Any]]:
    standard = problem["grading_standard"]
    if isinstance(standard, str):
        standard = json.loads(standard.replace("\\", "\\\\").replace(r"\\n", r"\n"))
    return standard


def final_answer_result(problem: dict[str, Any], matches: list[dict]) -> dict[str, Any]:
    standard = _grading_standard(problem)
    positions = [pos for pos, node in enumerate(standard) if node.get("is_final_answer", False)]
    if not positions and standard:
        positions = [len(standard) - 1]
    matched = {int(match["index_std"]) for match in matches}
    finals = [pos for pos in positions if pos in matched]
    return {"correct": bool(positions) and len(finals) == len(positions),
            "final_answer_score": len(finals) / len(positions) if positions else 0.0,
            "final_formula_count": len(positions), "matched_final_formula_count": len(finals)}


def _grade_child(connection, benchmark: str, row: dict[str, Any], response: str,
                 timeout: float, operation: str = "grade") -> None:
    os.setsid()
    if hasattr(os, "sched_getaffinity"):
        os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:4])
    try:
        # Upstream PRISM uses mp.cpu_count() rather than container affinity.
        # Restrict its pool in this child without editing upstream source.
        available = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count() or 1
        available = max(1, min(available, int(os.environ.get("SLURM_CPUS_PER_TASK", available))))
        multiprocessing.cpu_count = lambda: available
        runner = _native(benchmark)
        if operation == "historical_inputs":
            items = []
            if benchmark == "ugphysics":
                from utils import make_prompt

                for path in sorted(Path(row["data_dir"]).glob("*/en.jsonl")):
                    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
                    for index, problem in enumerate(records):
                        problem["_eval_id"] = f"{path.parent.name}/en/{index}"
                        items.append({"native": problem, "prompt": f"{make_prompt(problem)}\n\n{problem['problem']}",
                                      "question": problem["problem"],
                                      "reference_answer": f"{problem['solution']}\n\nReference answer:\n{problem['answers']}"})
                connection.send({"inputs": items, "grading_error": None})
                return
            from utils.data_utils import filter_and_convert
            from utils.prompt_utils import get_eval_prompt, get_problem_context, get_reference_solution

            for path in sorted(Path(row["data_dir"]).glob("*_cleaned_dag.json")):
                for raw in json.loads(path.read_text()):
                    if raw.get("images"):
                        continue
                    problem = filter_and_convert(raw)
                    if not problem:
                        continue
                    problem.update(_eval_id=f"{path.stem}:{problem['id']}", _dataset_file=path.name)
                    items.append({"native": problem, "prompt": get_eval_prompt(problem),
                                  "question": get_problem_context(problem),
                                  "reference_answer": get_reference_solution(problem)})
            connection.send({"inputs": items, "grading_error": None})
            return
        if operation == "auxiliary_prompt":
            judge = runner.Judger(strict_extract=True)
            student = judge.extract_ans(response)
            if not student:
                prompt = None
            else:
                student = judge.trans_plus_minus_sign(judge.split_by_comma(student))
                reference = judge.trans_plus_minus_sign(judge.split_by_comma(judge.extract_ans(row["answers"])))
                prompt = (JUDGE_PROMPT_PATH.read_text().replace("{{problem}}", row["problem"])
                          .replace("{{RS}}", row["solution"]).replace("{{RA}}", ", ".join(reference))
                          .replace("{{SS}}", response).replace("{{SA}}", ", ".join(student)))
            connection.send({"prompt": prompt, "grading_error": None})
            return
        if benchmark == "ugphysics":
            judge = runner.Judger(strict_extract=True)
            result = {
                "correct": bool(judge.auto_judge(response, row["answers"], precision=1e-2)),
                "extracted_answer": judge.extract_ans(response),
                "reference_answer": row["answers"],
            }
        elif benchmark == "phybench":
            normalized = normalize_latex(response)
            score, relative, size, distance = runner.EED(row["answer"], normalized)
            result = {"correct": bool(score == 100), "eed_score": float(score),
                      "relative_distance": float(relative), "tree_size": float(size),
                      "distance": float(distance), "reference_answer": row["answer"],
                      "final_answer": response, "normalized_final_answer": normalized}
        else:
            # The former simplifier change applied to reference formulas too.
            # Copy the row so presentation cleanup never mutates frozen inputs.
            grading_row = {**row, "grading_standard": [
                {**node, "formula": unwrap_presentation_macros(node["formula"])}
                for node in _grading_standard(row)
            ]}
            score, matches = runner.grade_problem_dag(grading_row, unwrap_presentation_macros(response))
            result = {"process_score": score, "matches": matches, **final_answer_result(row, matches)}
        connection.send({**result, "id": row["_eval_id"], "grading_error": None})
    except Exception as error:
        connection.send({
            "id": row.get("_eval_id"),
            "correct": False,
            "grading_error": f"{type(error).__name__}: {error}",
        })
    finally:
        connection.close()


def _run_child(benchmark: str, row: dict[str, Any], response: str,
               timeout: float, operation: str = "grade") -> dict[str, Any]:
    """Run one native grade with a hard timeout and no pipeline state mutation."""

    started = time.monotonic()
    context = multiprocessing.get_context("fork")
    receiver, sender = context.Pipe(duplex=False)
    child = context.Process(
        target=_grade_child, args=(sender, benchmark, row, response, timeout, operation)
    )
    child.start()
    sender.close()
    try:
        if receiver.poll(timeout + 5):
            try:
                result = receiver.recv()
            except EOFError:
                result = {"id": row.get("_eval_id"), "correct": False,
                          "grading_error": "Native scorer exited without returning a result"}
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


def grade_one(benchmark: str, row: dict[str, Any], response: str,
              timeout: float) -> dict[str, Any]:
    return _run_child(benchmark, row, response, timeout)


def auxiliary_prompt(row: dict[str, Any], response: str, timeout: float = 180.0) -> str | None:
    result = _run_child("ugphysics", row, response, timeout, "auxiliary_prompt")
    if result.get("grading_error"):
        raise RuntimeError(f"UGPhysics answer extraction failed: {result['grading_error']}")
    return result["prompt"]


def historical_inputs(benchmark: str, data_dir: Path, timeout: float = 180.0) -> list[dict[str, Any]]:
    """Prepare historical full-data scopes using upstream conversion/prompts."""
    if benchmark not in {"prism", "ugphysics"}:
        raise ValueError(f"No historical data converter for {benchmark}")
    result = _run_child(benchmark, {"data_dir": str(data_dir)}, "", timeout, "historical_inputs")
    if result.get("grading_error"):
        raise RuntimeError(f"{benchmark} data preparation failed: {result['grading_error']}")
    return result["inputs"]


def parse_verdict(report: str) -> bool:
    match = re.search(r"##\s*Equivalence Judgement\s*\n+\s*\**(TRUE|FALSE)\**",
                      report, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"Could not parse auxiliary verdict from report: {report[:300]!r}")
    return match.group(1).upper() == "TRUE"


def auxiliary_judge(row: dict[str, Any], response: str, model: str, timeout: float,
                    max_output_tokens: int, fable_model: str | None = None) -> dict[str, Any]:
    """Apply UGPhysics's released auxiliary prompt to an automatic-score failure."""

    prompt = auxiliary_prompt(row, response, timeout)
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
                system=SYSTEM_PROMPT,
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
            system_prompt=SYSTEM_PROMPT, strict_no_tools=True,
            max_exec_retries=0, max_tool_retries=0,
        ).complete(prompt)
        validate_codex_result(reply)
        report = reply.text
        result = {"usage": reply.usage, "actual_model": None}
    return {**result, "correct": parse_verdict(report), "judge_called": True,
            "report": report, "judge_model": model}
