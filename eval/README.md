# Physics evaluation

This package runs a resumable two-stage evaluation: model responses are cached
first, then judged. `merged` uses one final box and the row's `solution`;
`separated` uses one box and one judgment per detected part.

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

Dataset files are resolved from `final_datasets/<dataset>/<split>.parquet`, next
to the `eval` package. Supported datasets are `FrontierPhysics` and
`Physics`; supported splits are `train`, `validation`, and `test`.
`FrontierPhysics validation` is rejected because that split does not exist.

Artifacts live under `eval/artifacts/<dataset>/<split>/<mode>/model_<generator>/`.
The reusable generation cache is stored there as `responses.jsonl`. Judge-specific
`judgments.jsonl`, `summary.json`, and `run_config.json` live inside its
`judge_<judge>/` subdirectory.
JSONL files append after every completion and are reused on restart. Use
`--overwrite` for a fresh run. Rows run concurrently with 32 workers by default;
use `--max-workers` to change the limit.

Part IDs come directly from the finalized dataset's `ground_truths` JSON
dictionary keys, in dictionary order. These exact keys determine the generated
part labels, judge lookups, and score denominator, so gaps such as `b`, `d`, `f`
require no inference from question formatting. Both modes require
`ground_truths`; merged mode still uses `solution` as the answer reference.
