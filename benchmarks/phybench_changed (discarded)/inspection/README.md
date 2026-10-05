# PHYBench Inspection

Local viewer for the GPT-5.6-Sol-high best-of-five PHYBench evaluation. It only
loads the 100 answer-bearing PHYBench questions and their evaluation artifacts.

Run from the repository root:

```bash
/shared/data/home/aa3242/.local/bin/uv run benchmarks/phybench/inspection/server.py
```

Open `http://127.0.0.1:8766`. Use `--port` to select another port and
`--artifact-dir` to inspect another artifact directory with the same layout.
