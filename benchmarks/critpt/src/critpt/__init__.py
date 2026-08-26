"""
Cortex Benchmark - Private Package

Full package with generation AND evaluation.
DO NOT release publicly.

This is a SUPERSET of the public package.
"""

__version__ = "1.0.0"

from critpt.submission import Submission, SubmissionBatch, create_submission
from critpt.data_loader import BaseDataLoader, ProblemData, NotebookDataLoader


def critpt_generate(*args, **kwargs):
    """Load the Inspect-based generation pipeline only when it is requested."""
    from critpt.critpt_generate import critpt_generate as _critpt_generate

    return _critpt_generate(*args, **kwargs)

__all__ = [
    # Generation
    'Submission',
    'SubmissionBatch',
    'create_submission',
    'BaseDataLoader',
    'ProblemData',
    'NotebookDataLoader',
    'critpt_generate',
]
