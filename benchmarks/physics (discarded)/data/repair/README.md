# LLM Problem Repair

This folder contains a small repair runner for partially final-answerable physics
problems. It calls an OpenAI-compatible chat API or `utils.codex_cli.CodexLLM`
with `repair_prompt.txt`, checkpoints every row, and writes a repaired dataset.

Default input:

```text
data/repair/dev_set
```

Default output:

```text
data/repair/outputs/dev_set
```

Per-row repair checkpoints are written to:

```text
data/repair/repairs/dev_set
```

## Setup

```bash
python3 -m pip install -r data/repair/requirements.txt
```

Set API configuration:

```bash
export OPENAI_API_KEY=...
export OPENAI_MODEL=gpt-4o-mini
```

## Run On The Dev Set

OpenAI-compatible backend:

```bash
python3 data/repair/repair_dataset.py \
  --splits frontierphysics_test_partial_10.json
```

Codex CLI backend:

```bash
python3 data/repair/repair_dataset.py \
  --repair-backend codex-cli \
  --splits frontierphysics_test_partial_10.json
```

By default, the output writes the repaired problem into `question` and keeps
the input problem beside it:

```text
question
original_question
repair_status
```

Use `--output-mode add-columns` when you want to preserve the input `question`
field and add `repaired_question` instead.

Checkpoint files are append-only JSONL. Rerunning the same command with the same
`--repairs-dir` resumes completed rows and rebuilds the output file from the
checkpoint.
