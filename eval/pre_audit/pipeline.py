"""One problem/evaluator interface over the six pre-audit physics benchmarks."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import importlib
import json
from pathlib import Path
import shutil
import sys
from typing import Any, Callable, Iterable

from eval.datasets import DATA_ROOT, ROOT
from eval.storage import file_hash


DATASETS = ("phybench", "hle-physics", "prism", "ugphysics", "cmt", "critpt")
ALIASES = {
    "hle": "hle-physics",
    "cmt-benchmark": "cmt",
    "crit-pt": "critpt",
    "ug-physics": "ugphysics",
}
MANIFEST = DATA_ROOT / "manifest.json"


@dataclass(frozen=True)
class Problem:
    """A public problem plus the native-shaped row required by its scorer."""

    id: str
    question: str
    reference_answer: str
    prompt: str
    system_prompt: str | None = None
    category: str = ""
    response_format: str = "text"
    native: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def as_dict(self, *, include_reference: bool = True) -> dict[str, Any]:
        result = {
            "id": self.id,
            "question": self.question,
            "prompt": self.prompt,
            "system_prompt": self.system_prompt,
            "category": self.category,
            "response_format": self.response_format,
        }
        if include_reference:
            result["reference_answer"] = self.reference_answer
        return result

    def predictor_input(self) -> dict[str, Any]:
        """Return only fields that may be supplied to the evaluated model."""
        return {
            "id": self.id,
            "prompt": self.prompt,
            "system_prompt": self.system_prompt,
            "response_format": self.response_format,
        }


@dataclass(frozen=True)
class EvaluationResult:
    dataset: str
    id: str
    correct: bool
    score: float
    evaluator: str
    details: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "id": self.id,
            "correct": self.correct,
            "score": self.score,
            "evaluator": self.evaluator,
            "details": self.details,
        }


@dataclass(frozen=True)
class JudgeSettings:
    """Settings used only by benchmark evaluators that require an LLM judge."""

    model: str = "gpt-5.6-sol"
    reasoning_effort: str = "high"
    timeout: float = 1800.0
    max_output_tokens: int = 8192
    fable_model: str | None = None
    codex_bin: str = field(default_factory=lambda: shutil.which("codex") or str(Path.home() / ".local/bin/codex"))


# An injected judge is useful for embedding the adapter in another model runner
# and keeps unit tests/network policy outside the dataset layer.
Judge = Callable[[Problem, str], dict[str, Any]]


class PreAuditEvaluation:
    """A selected original dataset and the bridge to its original evaluator."""

    def __init__(self, dataset: str, problems: Iterable[Problem], metadata: dict[str, Any],
                 *, judge_settings: JudgeSettings | None = None, judge: Judge | None = None,
                 use_ugphysics_auxiliary: bool = True):
        self.dataset = dataset
        self.problems = tuple(problems)
        self.metadata = metadata
        self.judge_settings = judge_settings or JudgeSettings()
        self._judge = judge
        self.use_ugphysics_auxiliary = use_ugphysics_auxiliary
        self._by_id = {problem.id: problem for problem in self.problems}
        if not self.problems or len(self._by_id) != len(self.problems):
            raise ValueError(f"{dataset}: problems must be nonempty and uniquely identified")

    @property
    def questions(self) -> tuple[Problem, ...]:
        """Alias exposing the selected problems as the benchmark questions."""
        return self.problems

    def get(self, problem_id: str | int) -> Problem:
        try:
            return self._by_id[str(problem_id)]
        except KeyError:
            raise KeyError(f"Unknown {self.dataset} problem ID: {problem_id}") from None

    def evaluate(self, problem_id: str | int, response: str, *, timeout: float = 180.0) -> EvaluationResult:
        if not isinstance(response, str) or not response.strip():
            raise ValueError("response must be a nonempty string")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        problem = self.get(problem_id)
        if self.dataset in {"phybench", "prism", "ugphysics"}:
            result = _native_score(self.dataset, problem, response, timeout)
            if self.dataset != "ugphysics" or result.correct or not self.use_ugphysics_auxiliary:
                return result
            auxiliary = self._run_judge(problem, response, ugphysics=True)
            details = {"native": result.details, "auxiliary": auxiliary}
            correct = _judgment_correct(auxiliary)
            return EvaluationResult(self.dataset, problem.id, correct, float(correct),
                                    self.metadata["evaluator"], details)
        judgment = self._run_judge(problem, response)
        correct = _judgment_correct(judgment)
        return EvaluationResult(self.dataset, problem.id, correct, float(correct),
                                self.metadata["evaluator"], judgment)

    def evaluate_many(self, responses: dict[str, str], *, timeout: float = 180.0,
                      require_all: bool = False) -> list[EvaluationResult]:
        unknown = set(responses) - set(self._by_id)
        if unknown:
            raise ValueError(f"Unknown {self.dataset} response IDs: {sorted(unknown)}")
        if require_all and set(responses) != set(self._by_id):
            missing = [problem.id for problem in self.problems if problem.id not in responses]
            raise ValueError(f"Missing {self.dataset} responses: {missing}")
        return [self.evaluate(problem.id, responses[problem.id], timeout=timeout)
                for problem in self.problems if problem.id in responses]

    def _run_judge(self, problem: Problem, response: str, *, ugphysics: bool = False) -> dict[str, Any]:
        if self._judge is not None:
            result = self._judge(problem, response)
        elif ugphysics:
            result = _ugphysics_auxiliary_judge(problem, response, self.judge_settings)
        else:
            self._judge = _make_adapted_judge(self.dataset, self.judge_settings)
            result = self._judge(problem, response)
        _judgment_correct(result)
        return result


def load_benchmark(dataset: str, *, judge_settings: JudgeSettings | None = None,
                   judge: Judge | None = None,
                   use_ugphysics_auxiliary: bool = True) -> PreAuditEvaluation:
    """Load a pre-audit benchmark by name without importing its heavy scorer."""

    name = ALIASES.get(dataset.casefold(), dataset.casefold())
    if name not in DATASETS:
        raise ValueError(f"Unknown dataset {dataset!r}; choose one of {', '.join(DATASETS)}")
    problems, metadata = _load_snapshot(name)
    return PreAuditEvaluation(name, problems, metadata, judge_settings=judge_settings,
                             judge=judge, use_ugphysics_auxiliary=use_ugphysics_auxiliary)


def _load_snapshot(name: str) -> tuple[list[Problem], dict[str, Any]]:
    """Load one immutable, evaluation-ready original-data snapshot."""

    entry = json.loads(MANIFEST.read_text(encoding="utf-8"))["benchmarks"][name]["pre_audit"]
    source = DATA_ROOT / entry["file"]
    if file_hash(source) != entry["sha256"]:
        raise ValueError(f"Frozen pre-audit snapshot checksum changed: {source}")
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    problems = [Problem(
        str(row["id"]), row["question"], row["reference_answer"], row["prompt"],
        row.get("system_prompt"), row.get("category", ""),
        row.get("response_format", "text"), row.get("native", {}),
    ) for row in rows if row.get("reference_answer") is not None]
    if len(problems) != entry["evaluable_count"]:
        raise ValueError(f"{name}: evaluable count differs from data manifest")
    return problems, {
        "dataset": name,
        "count": len(problems),
        "source_count": entry["source_count"],
        "source": str(source.relative_to(ROOT)),
        "source_sha256": entry["sha256"],
        "evaluator": entry["evaluator"],
        "excluded_ids": [item["id"] for item in entry.get("excluded", [])],
        "excluded": entry.get("excluded", []),
        "selection": "frozen original-data evaluation set",
    }


def _parse_phybench_response(response: str) -> tuple[str, str | None]:
    try:
        value = json.loads(response)
    except json.JSONDecodeError:
        return "", "Expected a JSON object containing only final_answer"
    if not isinstance(value, dict) or set(value) != {"final_answer"} or not isinstance(value["final_answer"], str):
        return "", "Expected a JSON object containing only a string final_answer"
    return value["final_answer"], None


def _native_score(dataset: str, problem: Problem, response: str, timeout: float) -> EvaluationResult:
    scorer_response = response
    format_error = None
    if dataset == "phybench":
        scorer_response, format_error = _parse_phybench_response(response)
        if format_error:
            details = {"correct": False, "eed_score": 0.0,
                       "answer_format_error": format_error}
            return EvaluationResult(dataset, problem.id, False, 0.0,
                                    "PHYBench released EED; correct iff EED = 100", details)
    from . import native as bridge

    try:
        result = bridge.grade_one(dataset, problem.native, scorer_response, timeout)
    except Exception as error:
        raise RuntimeError(f"{dataset} native scorer process failed: {type(error).__name__}: {error}") from error
    if result.get("grading_error"):
        raise RuntimeError(
            f"{dataset} native scorer failed: {result['grading_error']}. "
            "Run with model_evals/fable/.venv/bin/python, which has the benchmark dependencies."
        )
    correct = bool(result["correct"])
    if dataset == "phybench":
        score = float(result["eed_score"]) / 100.0
    elif dataset == "prism":
        score = float(result["final_answer_score"])
    else:
        score = float(correct)
    return EvaluationResult(dataset, problem.id, correct, score, {
        "phybench": "PHYBench released EED; correct iff EED = 100",
        "prism": "PRISM released DAG grader; correct iff every final-answer DAG formula matches",
        "ugphysics": "UGPhysics released strict rule grader",
    }[dataset], result)


def _judge_args(settings: JudgeSettings) -> argparse.Namespace:
    return argparse.Namespace(
        judge_model=settings.model,
        judge_reasoning_effort=settings.reasoning_effort,
        judge_max_output_tokens=settings.max_output_tokens,
        timeout=settings.timeout,
        fable_model=settings.fable_model,
        codex_cli_path=ROOT / "utils",
        codex_bin=settings.codex_bin,
        use_tools=False,
        web_search="disabled",
        model="unused",
        reasoning_effort="high",
        claude_bin="claude",
    )


def _prepend_import(path: Path, package: str) -> ModuleType:
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)
    return importlib.import_module(package)


def _make_adapted_judge(dataset: str, settings: JudgeSettings) -> Judge:
    args = _judge_args(settings)
    if dataset == "hle-physics":
        module = importlib.import_module("benchmarks.hle.hle_eval.scoring")
        judge = module.make_judge(args)

        def evaluate(problem: Problem, response: str) -> dict[str, Any]:
            return judge({"id": problem.id, "question": problem.question},
                         {"response": response, "refused": False}, problem.reference_answer)
        return evaluate
    if dataset == "cmt":
        module = _prepend_import(ROOT / "analysis/CMT-Benchmark", "cmt_eval.scoring")
        judge = module.make_judge(args)

        def evaluate(problem: Problem, response: str) -> dict[str, Any]:
            return judge({"id": problem.id, "question": problem.question},
                         {"response": response, "refused": False}, problem.reference_answer)
        return evaluate
    if dataset == "critpt":
        module = _prepend_import(ROOT / "analysis/CritPt/scripts", "critpt_eval.backends")
        from benchmarks.hle.hle_eval.backends import resolve_fable_model

        judge = module.make_judge(args, {"api_model": resolve_fable_model(settings.fable_model)})

        def evaluate(problem: Problem, response: str) -> dict[str, Any]:
            return judge({"id": problem.id, "question": problem.question},
                         {"response": response, "refused": False}, problem.reference_answer)
        return evaluate
    raise ValueError(f"{dataset} does not use the HLE-adapted judge")


def _ugphysics_auxiliary_judge(problem: Problem, response: str,
                               settings: JudgeSettings) -> dict[str, Any]:
    from .native import auxiliary_judge

    return auxiliary_judge(problem.native, response, settings.model, settings.timeout,
                           settings.max_output_tokens, settings.fable_model)


def _judgment_correct(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        raise ValueError("Judge must return a dictionary")
    value = result.get("correct")
    if value is None and isinstance(result.get("judgment"), dict):
        value = result["judgment"].get("correct")
    if isinstance(value, bool):
        return value
    if value in {"yes", "no"}:
        return value == "yes"
    raise ValueError("Judge result must contain boolean correct or judgment.correct=yes/no")
