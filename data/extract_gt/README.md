# Exact ground-truth extraction

This pipeline asks `utils.codex_cli.CodexLLM` (`gpt-5.5`, reasoning effort
`high`) to map every question part to an answer assembled from tokens selected
from its worked solution. Answers may omit intervening text. Deterministic
validation requires their meaningful tokens (words, numbers, LaTeX commands,
and mathematical operators) to be an ordered subsequence of the solution's;
display delimiters and punctuation are ignored. A failed validation is sent back as retry
feedback; no answer that fails verification is written. The untrusted source `final_answers` field is removed from
both the development set and generated outputs, and is never shown to the LLM.

The checked-in `dev_set/` contains 10 rows from each requested test dataset. It
includes single-part questions, conventionally labeled solutions, and multi-part
questions whose solutions do not use matching `(a)`, `(b)`, ... labels.
`dev_set_train/` is a separate 10+10 development set drawn from the two training
splits with the same mixture of problem structures.

## Tests

```bash
rtk python3 -m unittest discover -s data/extract_gt -p 'test_*.py'
```

## Dev-set run (only after approval)

```bash
rtk /home/alliiance/.local/bin/uv run --with pyarrow python3 \
  data/extract_gt/extract_ground_truths.py --workers 2
```

Outputs mirror each input filename under `data/extract_gt/outputs/dev_set/`.
For parquet stability, `ground_truths` is stored as a JSON string;
JSON/JSONL outputs store it as an object. Existing outputs are protected unless
`--overwrite` is supplied. A row that still fails after three LLM attempts is
omitted from the parquet output and recorded in `<output_stem>_failures.jsonl`.
Successfully extracted but unanswerable parts have JSON `null` values; their
reasons, full questions, isolated sub-questions, sample IDs, and dataset IDs are
written separately in `<output_stem>_null_answers.jsonl`.
