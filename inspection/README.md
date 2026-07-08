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

The server discovers parquet files under `filtered_datasets/` and jsonl files under `original_datasets/`.
Use the search box to filter samples by phrase in the `question` field.
