# Dataset Inspection Tool

A small local web app for browsing dataset samples and inspecting every field in a readable dialog.

## Run

From the project root:

```bash
/home/alliiance/.local/bin/uv run inspection/server.py
```

Then open:

```text
http://127.0.0.1:8765
```

The server discovers parquet files under `filtered_datasets/` and `repaired_datasets/`, plus original prepared `test.parquet` files under `original_datasets/` and the archived originals in `backup/0_original_datasets/`. It also exposes curated original-test ground-truth extraction issues and extracted ground truths from `data/extract_gt/outputs/dev_set*/` as prominent dataset choices. Each part is shown separately with KaTeX-rendered mathematics and expandable selected source content.
Use the search box to filter samples by phrase in the `question` field.
