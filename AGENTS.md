# Repository Guidelines

## Project Structure & Module Organization

This repository contains Python pipelines and parquet datasets for physics LLM
evaluation. `eval/` is the main package, with CLI entrypoint `python -m eval`,
pipeline modules, and tests in `eval/tests/`. `data/` contains preparation
workflows: `extract_gt/`, `filter/`, `partition/`, and `repair/`. `inspection/`
is a local web app for reviewing parquet rows. `final_datasets/` holds current
scored datasets; `backup/` preserves earlier states. `utils/` contains shared
helpers such as the Codex CLI wrapper. Keep one-off analysis in `scratch/` or
`leftovers/`.

## Build, Test, and Development Commands

- `rtk /home/alliiance/.local/bin/uv run --with pyarrow python -m eval FrontierPhysics test --mode merged --limit 1` runs a one-row evaluation smoke test.
- `rtk python3 -m unittest discover -s eval/tests -p 'test_*.py'` runs evaluation unit tests.
- `rtk python3 -m unittest discover -s data/extract_gt -p 'test_*.py'` runs ground-truth extraction tests.
- `rtk python3 -m pip install -r data/filter/requirements.txt` installs filter pipeline dependencies.
- `rtk /home/alliiance/.local/bin/uv run inspection/server.py` starts the inspection UI at `http://127.0.0.1:8765`.

For Codex-managed shell work in this repository, prefix commands with `rtk`.

## Evaluation Mode Policy

Use merged mode for all new evaluations. Separated mode is deprecated and
disabled in the evaluator; `--mode separated` raises `ValueError` to avoid
wasting tokens on obsolete per-part extraction and judging runs.

## Coding Style & Naming Conventions

Use Python 3 with 4-space indentation. Follow existing style: `snake_case` for
functions, modules, and variables; `CamelCase` for classes; `ALL_CAPS` for
schemas/constants. Prefer `pathlib.Path`, explicit JSON/parquet handling, and
small pure helpers around parsing or scoring logic. Keep prompts in text files
under the relevant workflow directory. Avoid mixing dataset generation,
inspection UI, and evaluation concerns in the same module.

## Testing Guidelines

Tests use the standard `unittest` framework and should be named `test_*.py`.
Add focused tests for parsing, cache/resume behavior, scoring summaries, and
dataset path validation. For LLM or API workflows, keep a small `--limit` smoke
command in the relevant README and avoid network calls in unit tests.

## Commit & Pull Request Guidelines

Recent commits use short imperative subjects such as `Update README` and `Add
repeated eval attempts`. Keep commits scoped to one workflow or behavior change.
Pull requests should describe the dataset split or pipeline affected, list test
commands run, and call out generated artifacts, cache invalidation, or required
API keys. Include screenshots only for `inspection/` UI changes.

## Security & Configuration Tips

Do not commit `.env`, API keys, or provider credentials. Prefer environment
variables such as `OPENAI_API_KEY`, `OPENAI_MODEL`, and `OPENAI_BASE_URL`.
Large generated artifacts should live under documented artifact/output
directories and be resumable or reproducible from checked-in inputs.
