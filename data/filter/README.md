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

## Change The Filtering Rule

Edit `data/filter/prompts/final_answerable.txt`. The prompt must ask for a JSON
object containing:

```json
{"keep": true, "label": "final_answerable", "reason": "short reason"}
```

Rows with `keep: true` are written to the filtered parquet split. Per-row judge
decisions are written to the configured `--decisions-dir`.
