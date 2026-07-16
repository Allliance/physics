# Physics evaluation

This package runs a resumable two-stage evaluation: model responses are cached
first, then judged. `merged` uses one final box and the row's `solution`, with
the judge inferring parts from the problem and solution; `separated` uses one
box and one judgment per detected part.
The default mode is `merged`; pass `--mode separated` only when separated
per-part extraction and scoring is specifically needed.

Run one-row Codex smoke tests:

```bash
uv run --with pyarrow python -m eval FrontierPhysics test --mode merged --limit 1
uv run --with pyarrow python -m eval FrontierPhysics test --mode separated --limit 1
```

Run against an OpenAI-compatible or vLLM chat-completions endpoint:

```bash
uv run --with pyarrow python -m eval Physics test --mode separated \
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
`judge_<judge>/` subdirectory. Judge rows include per-part reasons in `parts`:
separated mode stores the reason for the single part judged by each judge call,
while merged mode stores one reason and one score for every part inferred by
the single merged judgment. Merged part scores are `1` for correct, `0` for
incorrect, and `null` when the reference solution is not comprehensible enough
to judge that part. The merged row score is the sum of non-null part scores
divided by the number of non-null part scores.
JSONL files append after every completion and are reused on restart. Use
`--overwrite` for a fresh run. Rows run concurrently with 32 workers by default;
use `--max-workers` to change the limit.
When `--repeat K` is greater than 1, `summary.json` keeps `mean_score` as the
first-attempt mean and also reports `mean@K`/`mean_at_K` and
`best@K`/`best_at_K`. These are computed per problem across all K scored
attempts, then averaged across problems.

In separated mode, part IDs come from the finalized dataset's `ground_truths`
JSON dictionary keys, in dictionary order, excluding keys whose value is null.
These exact keys determine the generated part labels, judge lookups, and score
denominator, so gaps such as `b`, `d`, `f` require no inference from question
formatting. Rows with no non-null ground-truth parts are skipped. Merged mode
does not use `ground_truths`; rows with no `solution` are skipped.
For a preserved single sub-question (`is_multi_part=false`), the sole part is
canonicalized to `a` even when the question or model answer retains an original
label such as `(b)` or `(c)`. Genuine multipart rows keep their original part
identifiers.
