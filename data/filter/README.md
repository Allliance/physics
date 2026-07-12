# LLM Dataset Filter

This folder contains a small OpenAI-compatible LLM judge pipeline for filtering
prepared parquet datasets.

Default input:

```text
original_datasets/prepared/FrontierPhysics
```

Default output:

```text
filtered_datasets/prepared/FrontierPhysics
```

The output directory mirrors the input split files, for example `train.parquet`
and `test.parquet`, and keeps the original parquet columns/schema.

Judge decision logs are written separately by default:

```text
data/filter/decisions/FrontierPhysics
```

## Setup

```bash
python3 -m pip install -r data/filter/requirements.txt
```

Set API configuration:

```bash
export OPENAI_API_KEY=...
export OPENAI_MODEL=gpt-4o-mini
# Optional for non-OpenAI providers:
export OPENAI_BASE_URL=https://your-provider.example/v1
```

## Run

```bash
bash data/filter/run_frontierphysics_filter.sh
```

Useful smoke test:

```bash
python3 data/filter/filter_dataset.py --limit 5 --output-dir /tmp/frontier-filter-smoke
```

Run the labeled dev set with Codex CLI as the judge:

```bash
python3 data/filter/filter_dataset.py \
  --judge-backend codex-cli \
  --workers 32 \
  --input-dir data/filter/dev_sets \
  --splits physics_test_labeled.parquet \
  --output-dir /tmp/physics-dev-filtered \
  --decisions-dir /tmp/physics-dev-decisions
```

## Development Set

A small labeled Physics test set is available for prompt/filter debugging:

```text
data/filter/dev_sets/physics_test_labeled.json
data/filter/dev_sets/physics_test_labeled.parquet
```

Each row has `label` using the same taxonomy requested from the judge:

```text
fully_final_answerable
partial_final_answerable
non_final_answerable
```

The filter prompt input intentionally excludes `label`.

## Change The Filtering Rule

Edit `data/filter/prompts/final_answerable.txt`. The prompt must ask for a JSON
object containing:

```json
{
  "verdict": "fully_final_answerable",
  "keep": true,
  "reason": "short reason"
}
```

Rows with `keep: true` are written to the filtered parquet split. Per-row judge
decisions are written to the configured `--decisions-dir`.

Decision logs are append-only checkpoints. Each completed row is written and
fsynced immediately, so an interrupted run can be resumed by rerunning the same
command with the same `--input-dir`, `--splits`, and `--decisions-dir`. Existing
valid row decisions are skipped, and parquet outputs are rebuilt from the
checkpoint when the split finishes.

## Codex CLI As A Small LLM API

`utils/codex_cli` wraps `codex exec` behind a small Python interface.
It is useful when you want to call Codex from scripts without using the
interactive UI.

```bash
python3 -m utils.codex_cli "Return a JSON object with keep=true."
```

Or from Python:

```python
from utils.codex_cli import CodexLLM

client = CodexLLM(model="gpt-5.4", timeout=120, max_tool_retries=3)
result = client.complete("Classify this problem as keep or drop.")
print(result.text)
```

The wrapper runs:

```text
codex exec --json --ephemeral --ignore-user-config --ignore-rules
```

with an empty temporary working directory, `read-only` sandbox,
`--ask-for-approval never`, disabled web search, no project docs, and disabled
multi-agent feature. It also parses Codex JSONL events and raises an error if
Codex emits a shell, file-change, MCP, or web-search tool event.

By default, tool-use failures are retried up to 3 times before raising
`CodexToolRetryError`. Set `max_tool_retries=0` or pass `--max-tool-retries 0`
to fail on the first tool-use event.

The Codex CLI docs do not currently expose a single flag that removes every
tool from the model interface. This wrapper keeps the prompt short and enforces
no-tool behavior at the event layer.
