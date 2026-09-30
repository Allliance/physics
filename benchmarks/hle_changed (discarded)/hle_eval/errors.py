"""Distinguish exhausted generation budgets from retryable execution failures."""


class GenerationLimitError(ValueError):
    """The evaluated attempt exhausted a generation/session/platform limit."""
