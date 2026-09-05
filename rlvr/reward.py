"""Dataset-dispatched rule rewards for physics RLVR with verl.

The public ``compute_score`` signature is the custom reward ABI expected by
verl. Ground truths are JSON strings produced by ``rlvr.prepare_data``. Native
benchmark graders are loaded lazily so importing this module stays cheap and
so PRISM's and UGPhysics's conflicting top-level ``utils`` modules do not leak
into one another.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import signal
import subprocess
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator


REPO_ROOT = Path(__file__).resolve().parents[1]
PRISM_ROOT = REPO_ROOT / "benchmarks" / "prism"
UGPHYSICS_CODE_ROOT = REPO_ROOT / "benchmarks" / "ugphysics" / "codes"

PRISM_SOURCE = "physics/prism"
UGPHYSICS_SOURCE = "physics/ugphysics"

_PRISM_RESULT_PREFIX = "RLVR_PRISM_RESULT="
_UGPHYSICS_RESULT_PREFIX = "RLVR_UGPHYSICS_RESULT="

_PRISM_TOOLS: tuple[Callable[..., Any], Callable[..., Any], Callable[..., Any]] | None = None
_UGPHYSICS_JUDGER: Any | None = None
_REWARD_DEPS_ACTIVE = False


@contextmanager
def _timeout(seconds: float | None) -> Iterator[None]:
    """Bound symbolic grading when called from a process main thread."""
    if not seconds or seconds <= 0:
        yield
        return

    def handler(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"physics reward exceeded {seconds:g} seconds")

    previous = signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _remove_top_level_modules(names: tuple[str, ...]) -> None:
    for module_name in tuple(sys.modules):
        if any(module_name == name or module_name.startswith(f"{name}.") for name in names):
            sys.modules.pop(module_name, None)


def _activate_reward_dependencies() -> None:
    """Use grader-only packages without replacing verl's own dependencies.

    Hydra/OmegaConf requires ANTLR 4.9 while modern SymPy's LaTeX parser
    requires 4.11. The Slurm launcher installs the latter into a separate
    target directory; reward workers are dedicated processes, so selecting it
    here cannot disturb verl's controller processes.
    """
    global _REWARD_DEPS_ACTIVE
    if _REWARD_DEPS_ACTIVE:
        return
    dependency_root = os.environ.get("RLVR_REWARD_DEPS")
    if dependency_root and Path(dependency_root).is_dir():
        _remove_top_level_modules(("antlr4",))
        sys.path.insert(0, dependency_root)
    _REWARD_DEPS_ACTIVE = True


def _load_prism_tools() -> tuple[Callable[..., Any], Callable[..., Any], Callable[..., Any]]:
    global _PRISM_TOOLS
    if _PRISM_TOOLS is not None:
        return _PRISM_TOOLS
    _activate_reward_dependencies()
    _remove_top_level_modules(("utils",))
    sys.path.insert(0, str(PRISM_ROOT))
    try:
        from utils.formula_comparison_utils import whether_rel_latex_correct_with_units
        from utils.grade_utils import extract_equations
        from utils.numerical_utils import analyze_formula
    finally:
        sys.path.pop(0)
    _PRISM_TOOLS = (extract_equations, analyze_formula, whether_rel_latex_correct_with_units)
    return _PRISM_TOOLS


def _load_ugphysics_judger() -> Any:
    global _UGPHYSICS_JUDGER
    if _UGPHYSICS_JUDGER is not None:
        return _UGPHYSICS_JUDGER
    _activate_reward_dependencies()
    _remove_top_level_modules(("utils", "judge", "math_equivalence"))
    sys.path.insert(0, str(UGPHYSICS_CODE_ROOT))
    try:
        from judge import Judger

        _UGPHYSICS_JUDGER = Judger(strict_extract=True)
    finally:
        sys.path.pop(0)
    return _UGPHYSICS_JUDGER


def _ground_truth_object(ground_truth: Any) -> dict[str, Any]:
    if isinstance(ground_truth, dict):
        return ground_truth
    if isinstance(ground_truth, str):
        parsed = json.loads(ground_truth)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("ground_truth must be a JSON object or encoded JSON object")


def _has_prism_format(solution: str) -> bool:
    return bool(re.search(r"\$\$.+?\$\$", solution, flags=re.DOTALL))


def _has_boxed_answer(solution: str) -> bool:
    return "\\boxed{" in solution or "\\fbox{" in solution


def _prism_components(solution: str, truth: dict[str, Any]) -> tuple[float, float]:
    """Run a bounded, non-forking form of PRISM's released DAG grader.

    The released grader creates a multiprocessing pool for every answer. That
    deadlocks when a symbolic timeout fires inside a Ray actor, so reward
    workers use the same extraction, numeric tolerance, and symbolic comparator
    sequentially. Candidate equations are bounded to keep RL step latency
    predictable.
    """
    extract_equations, analyze_formula, compare_formula = _load_prism_tools()
    standard = copy.deepcopy(truth["grading_standard"])
    if isinstance(standard, str):
        standard = json.loads(standard.replace("\\", "\\\\").replace(r"\\n", r"\n"))
    if not isinstance(standard, list) or not standard:
        return 0.0, 0.0

    standard_formulas = [str(node["formula"]).replace("$", "") for node in standard]
    answer_formulas = extract_equations(solution)
    max_candidates = max(1, int(os.environ.get("RLVR_PRISM_MAX_ANSWER_EQUATIONS", "12")))
    if len(answer_formulas) > max_candidates:
        # Preserve a little early reasoning while favoring the final equations.
        early_count = min(4, max_candidates // 4)
        answer_formulas = answer_formulas[:early_count] + answer_formulas[-(max_candidates - early_count) :]

    matched = [False] * len(standard_formulas)
    directly_matched: set[int] = set()
    for standard_index, standard_formula in enumerate(standard_formulas):
        for answer_formula in answer_formulas:
            try:
                epsilon = max(analyze_formula(standard_formula), analyze_formula(answer_formula), 1e-5)
                correct, _reason = compare_formula(
                    standard_formula, answer_formula, epsilon_for_equal=epsilon
                )
            except TimeoutError:
                raise
            except Exception:
                continue
            if correct:
                matched[standard_index] = True
                directly_matched.add(standard_index)
                break

    index_to_position = {int(node["index"]): position for position, node in enumerate(standard)}
    propagated: set[int] = set()

    def mark_dependencies(position: int) -> None:
        if position in propagated:
            return
        propagated.add(position)
        for dependency in standard[position].get("dependency", []):
            dependency_position = index_to_position.get(int(dependency))
            if dependency_position is not None:
                mark_dependencies(dependency_position)

    for position, is_matched in enumerate(matched):
        if is_matched:
            mark_dependencies(position)

    process_score = len(propagated) / len(standard)
    finals = [index for index, node in enumerate(standard) if node.get("is_final_answer", False)]
    if not finals:
        finals = [len(standard) - 1]
    final_score = sum(index in directly_matched for index in finals) / len(finals)
    return float(process_score), final_score


def score_prism(solution: str, truth: dict[str, Any]) -> dict[str, float]:
    process_score, final_score = _prism_components(solution, truth)
    format_score = float(_has_prism_format(solution))
    # A correct final answer dominates; process matching supplies useful dense
    # signal, while the small format term teaches the released grader's syntax.
    score = 0.75 * final_score + 0.23 * process_score + 0.02 * format_score
    return {
        "score": float(min(1.0, max(0.0, score))),
        "acc": float(math.isclose(final_score, 1.0)),
        "final_answer_score": float(final_score),
        "process_score": float(process_score),
        "format_score": format_score,
        "reward_timeout": 0.0,
        "reward_resource_limit": 0.0,
        "reward_error": 0.0,
    }


def _isolated_prism_failure(metric: str) -> dict[str, float]:
    result = {
        "score": 0.0,
        "acc": 0.0,
        "final_answer_score": 0.0,
        "process_score": 0.0,
        "format_score": 0.0,
        "reward_timeout": 0.0,
        "reward_resource_limit": 0.0,
        "reward_error": 0.0,
    }
    result[metric] = 1.0
    return result


def _score_prism_isolated(
    solution: str, truth: dict[str, Any], timeout_seconds: float
) -> dict[str, float]:
    """Grade one PRISM response in a disposable, resource-capped process.

    Some malformed model equations make SymPy consume memory without bound.
    A signal timeout does not reclaim that memory from a persistent Ray actor,
    so every PRISM attempt runs in a fresh child. The child applies RLIMIT_AS
    before importing SymPy and the parent enforces a separate wall deadline.
    """
    request = json.dumps({"solution": solution, "truth": truth})
    environment = os.environ.copy()
    environment["RLVR_PRISM_CHILD_TIMEOUT_SECONDS"] = str(timeout_seconds)
    environment["OPENBLAS_NUM_THREADS"] = "1"
    environment["OMP_NUM_THREADS"] = "1"
    environment["MKL_NUM_THREADS"] = "1"
    process = subprocess.Popen(
        [sys.executable, "-m", "rlvr.prism_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=environment,
    )
    try:
        stdout, stderr = process.communicate(
            request,
            timeout=max(1.0, timeout_seconds) + 2.0,
        )
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        return _isolated_prism_failure("reward_timeout")

    result_line = next(
        (line for line in reversed(stdout.splitlines()) if line.startswith(_PRISM_RESULT_PREFIX)),
        None,
    )
    if result_line is None:
        if os.environ.get("RLVR_REWARD_DEBUG") == "1":
            print(
                f"[physics-reward] PRISM child exited {process.returncode}: {stderr[-2000:]}",
                file=sys.stderr,
                flush=True,
            )
        metric = "reward_resource_limit" if process.returncode in (-9, -24) else "reward_error"
        return _isolated_prism_failure(metric)

    response = json.loads(result_line.removeprefix(_PRISM_RESULT_PREFIX))
    if response.get("error") == "timeout":
        return _isolated_prism_failure("reward_timeout")
    if response.get("error") == "memory":
        return _isolated_prism_failure("reward_resource_limit")
    if "error" in response:
        if os.environ.get("RLVR_REWARD_DEBUG") == "1":
            print(
                f"[physics-reward] PRISM child error: {response['error']}",
                file=sys.stderr,
                flush=True,
            )
        return _isolated_prism_failure("reward_error")
    result = response.get("result")
    if not isinstance(result, dict):
        return _isolated_prism_failure("reward_error")
    return {str(key): float(value) for key, value in result.items()}


def score_ugphysics(solution: str, truth: dict[str, Any]) -> dict[str, float]:
    judger = _load_ugphysics_judger()
    # Prepared datasets historically stored the released boxed target in
    # ``answers``. The audited validation set stores a complete worked solution
    # in ``reference_answer`` instead; UGPhysics's extractor accepts either and
    # pulls the final boxed expression before applying symbolic equivalence.
    reference = truth.get("answers", truth.get("reference_answer"))
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("UGPhysics ground truth needs answers or reference_answer")
    correct = bool(judger.auto_judge(solution, reference, precision=1e-2))
    format_score = float(_has_boxed_answer(solution))
    score = 1.0 if correct else 0.05 * format_score
    return {
        "score": score,
        "acc": float(correct),
        "format_score": format_score,
        "reward_timeout": 0.0,
        "reward_resource_limit": 0.0,
        "reward_error": 0.0,
    }


def _score_ugphysics_isolated(
    solution: str, truth: dict[str, Any], timeout_seconds: float
) -> dict[str, float]:
    """Grade one UGPhysics response in a disposable bounded process."""
    request = json.dumps({"solution": solution, "truth": truth})
    environment = os.environ.copy()
    environment["RLVR_UGPHYSICS_CHILD_TIMEOUT_SECONDS"] = str(timeout_seconds)
    environment["OPENBLAS_NUM_THREADS"] = "1"
    environment["OMP_NUM_THREADS"] = "1"
    environment["MKL_NUM_THREADS"] = "1"
    process = subprocess.Popen(
        [sys.executable, "-m", "rlvr.ugphysics_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=environment,
    )
    try:
        stdout, stderr = process.communicate(
            request,
            timeout=max(1.0, timeout_seconds) + 2.0,
        )
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        return _reward_failure(UGPHYSICS_SOURCE, "reward_timeout")

    result_line = next(
        (line for line in reversed(stdout.splitlines()) if line.startswith(_UGPHYSICS_RESULT_PREFIX)),
        None,
    )
    if result_line is None:
        if os.environ.get("RLVR_REWARD_DEBUG") == "1":
            print(
                f"[physics-reward] UGPhysics child exited {process.returncode}: {stderr[-2000:]}",
                file=sys.stderr,
                flush=True,
            )
        metric = "reward_resource_limit" if process.returncode in (-9, -24) else "reward_error"
        return _reward_failure(UGPHYSICS_SOURCE, metric)

    response = json.loads(result_line.removeprefix(_UGPHYSICS_RESULT_PREFIX))
    if response.get("error") == "timeout":
        return _reward_failure(UGPHYSICS_SOURCE, "reward_timeout")
    if response.get("error") == "memory":
        return _reward_failure(UGPHYSICS_SOURCE, "reward_resource_limit")
    if "error" in response:
        return _reward_failure(UGPHYSICS_SOURCE, "reward_error")
    result = response.get("result")
    if not isinstance(result, dict):
        return _reward_failure(UGPHYSICS_SOURCE, "reward_error")
    return {str(key): float(value) for key, value in result.items()}


def _reward_failure(data_source: str, metric: str) -> dict[str, float]:
    if data_source == PRISM_SOURCE:
        return _isolated_prism_failure(metric)
    result = {
        "score": 0.0,
        "acc": 0.0,
        "format_score": 0.0,
        "reward_timeout": 0.0,
        "reward_resource_limit": 0.0,
        "reward_error": 0.0,
    }
    result[metric] = 1.0
    return result


def compute_score(
    data_source: str,
    solution_str: str,
    ground_truth: Any,
    extra_info: dict[str, Any] | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, float]:
    """Compute a safe rule reward for any supported physics dataset."""
    del extra_info
    try:
        truth = _ground_truth_object(ground_truth)
        if data_source == PRISM_SOURCE:
            if os.environ.get("RLVR_PRISM_ISOLATE", "1") != "0":
                return _score_prism_isolated(solution_str, truth, timeout_seconds)
            with _timeout(timeout_seconds):
                return score_prism(solution_str, truth)
        if data_source == UGPHYSICS_SOURCE:
            if os.environ.get("RLVR_UGPHYSICS_ISOLATE", "1") != "0":
                return _score_ugphysics_isolated(solution_str, truth, timeout_seconds)
            with _timeout(timeout_seconds):
                return score_ugphysics(solution_str, truth)
        with _timeout(timeout_seconds):
            raise ValueError(f"unsupported physics reward data_source: {data_source!r}")
    except TimeoutError:
        return _reward_failure(data_source, "reward_timeout")
    except Exception as exc:
        # Malformed model generations must not kill a long-running RL job.
        print(
            f"[physics-reward] {data_source}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc(file=sys.stderr)
        if os.environ.get("RLVR_REWARD_RAISE_ERRORS") == "1":
            raise
        return _reward_failure(data_source, "reward_error")
