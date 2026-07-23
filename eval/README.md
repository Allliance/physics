# Physics evaluation

This package runs a resumable two-stage evaluation: model responses are cached
first, then judged. `merged` uses one final box and the row's `solution`, with
the judge inferring parts from the problem and solution.
The default and supported evaluation mode is `merged`.

Separated mode is deprecated and disabled. Passing `--mode separated` raises
`ValueError`; do not use it for new evaluations.

Run one-row Codex smoke tests:

```bash
uv run --with pyarrow python -m eval FrontierPhysics test --mode merged --limit 1
```

Run against an OpenAI-compatible or vLLM chat-completions endpoint:

```bash
uv run --with pyarrow python -m eval Physics test --mode merged \
  --generator-backend openai --generator-url http://localhost:8000 \
  --generator-model my-model --generator-api-key EMPTY \
  --judge-backend openai --judge-url https://api.openai.com \
  --judge-model gpt-5.5 --judge-api-key "$OPENAI_API_KEY"
```

Reasoning-capable OpenAI-compatible endpoints can use
`--generator-reasoning-effort high`; cap generated tokens with
`--generator-max-tokens 32768`.
Use `--repeat K` to run K independent generation-plus-judgment attempts for
each selected problem. The default is `--repeat 1`, matching the legacy one
attempt behavior. Attempt 1 keeps the legacy cache key; later attempts are
stored in the same `responses.jsonl` and `judgments.jsonl` files with derived
attempt keys plus `row_key` and `attempt` metadata, so repeat runs are
resumable and can reuse existing first-attempt artifacts.

Dataset files are resolved from `final_datasets/<dataset>/<split>.parquet`, next
to the `eval` package. Supported datasets are `FrontierPhysics` and
`Physics`; supported splits are `train`, `validation`, and `test`.
`FrontierPhysics validation` is rejected because that split does not exist.

Artifacts live under
`eval/artifacts/<dataset>/<split>/<mode>/model_<generator>_gen_<config-hash>/`.
The hash covers the full generation configuration, preventing responses made
with different reasoning or sampling settings from sharing a cache.
The reusable generation cache is stored there as `responses.jsonl`. Judge-specific
`judgments.jsonl`, `summary.json`, and `run_config.json` live inside its
`judge_<judge>/` subdirectory. Judge rows include one reason and one score for
every part inferred by the single merged judgment. If a dataset row has a
non-empty `target_parts` list, the merged judge is instead instructed to score
exactly those parts, and the row score is the sum of those target part scores
divided by the length of `target_parts`. For rows without `target_parts`, part
scores are `1` for correct, `0` for incorrect, and `null` when the reference
solution is not comprehensible enough to judge that part. The row score is the
sum of non-null part scores divided by the number of non-null part scores. The
default merged judge prompt treats the reference solution as the gold standard
and tells the judge not to override it when it suspects the reference is wrong or
contains a typo. `--judge-prompt strict-reference` preserves the same strict
reference policy in a separate `prompt_strict-reference-gold` artifact directory.
JSONL files append after every completion and are reused on restart. Use
`--overwrite` for a fresh run. Rows run concurrently with 32 workers by default;
use `--max-workers` to change the limit.
When `--repeat K` is greater than 1, `summary.json` keeps `mean_score` as the
first-attempt mean and also reports `mean@K`/`mean_at_K` and
`best@K`/`best_at_K`. These are computed per problem across all K scored
attempts, then averaged across problems.

Merged mode does not use `ground_truths`; rows with no `solution` are skipped.
