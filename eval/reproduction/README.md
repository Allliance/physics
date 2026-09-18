# Historical reproduction launchers

These are optional, hard-coded launchers retained for provenance of saved paper
results. They are not the general evaluation API.

- `native_selected_mean4.py` runs three models, four attempts, and the three
  selected public-source benchmarks with their native prompts/evaluators.
- `selected_mean4.py` runs the same fixed matrix on original data with the
  unified HLE-adapted evaluator.

For a new model or for all six benchmarks, use `python -m eval pre-audit run` or
`python -m eval post-audit` as documented in the parent README.
