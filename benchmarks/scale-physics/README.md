# ScalePhysics

ScalePhysics is the English-language subset of the upstream `desimfj/PHYSICS`
test split used by this repository's evaluation pipeline.

The prepared dataset is stored at `data/test.parquet`. Rebuild it from the
upstream dataset with:

```bash
python benchmarks/scale-physics/prepare.py
```

Run the default reproducible 100-question GPT-5.6-Sol evaluation with:

```bash
uv run --with pyarrow python benchmarks/scale-physics/evaluate.py
```

The evaluator samples without replacement using seed `5600`, saves the sample
manifest, responses, judgments, failures, configuration, and summary under
`results/`, and resumes cached work when rerun. Override `--sample-size`,
`--seed`, `--model`, reasoning effort, concurrency, or output location through
CLI flags; run `python benchmarks/scale-physics/evaluate.py --help` for details.

To compute adaptive pass@5 from that run, giving only still-unsolved problems
another chance in each round, run:

```bash
uv run --with pyarrow python benchmarks/scale-physics/run_pass_at_5.py
```

Attempts 2--5 are stored separately and `pass_at_5_summary.json` reports both
per-round counts and cumulative pass@1 through pass@5.
