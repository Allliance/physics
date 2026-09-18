"""Unified access to the frozen pre-audit physics benchmark evaluations.

The public entry point is :func:`load_benchmark`.  Dataset-specific source rows
remain attached to each problem so the bridge can call the benchmark scorer
without translating the reference into a new grading format.
"""

from .pipeline import (
    DATASETS,
    EvaluationResult,
    PreAuditEvaluation,
    JudgeSettings,
    Problem,
    load_benchmark,
)

__all__ = [
    "DATASETS",
    "EvaluationResult",
    "PreAuditEvaluation",
    "JudgeSettings",
    "Problem",
    "load_benchmark",
]
