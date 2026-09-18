# Physics evaluation pipeline

`eval` is the single entry point for fresh evaluations on all six benchmarks.
It deliberately separates two protocols:

- **Pre-audit:** original benchmark material and benchmark-specific evaluation.
  PHYBench uses EED, PRISM uses its released DAG grader, and UGPhysics uses its
  rule grader plus auxiliary equivalence judge. HLE-Physics uses the HLE judge;
  CMT and CritPt use the HLE-adapted judge because their original automatic
  per-question graders are unavailable.
- **Post-audit:** reviewed data with benchmark-error questions excluded (and
  repairable CMT/CritPt questions repaired), using one HLE-adapted merged binary
  equivalence judge for every benchmark.

Both protocols generate fresh answers, checkpoint every stage, keep references
out of model inputs, support one benchmark or all six, and support repeated
attempts for `mean@n` and `pass@n`. Generation and judging are no-tool in this
runner. Historical tool-enabled paper runs remain in their benchmark artifact
directories and are not silently mixed with new no-tool runs.

## Data

All built-in runtime inputs are immutable snapshots under [`data/`](data/README.md).
The pipeline does not assemble datasets from scattered repository files while a
run is in progress.

| Benchmark | Pre-audit evaluated | Post-audit evaluated |
|---|---:|---:|
| `phybench` | 100 | 87 |
| `hle-physics` (`hle`) | 202 | 116 |
| `prism` | 100 selected | 74 |
| `ugphysics` | 100 selected | 82 |
| `cmt` | 50 | 49 |
| `critpt` | 55 with original references | 54 |

The CritPt archive contains all 71 original rows; 16 lack public original
references and therefore cannot be graded locally. Its post-audit set is the 54
retained rows from the 56 audited challenges. The paper's pre-audit CritPt score
is Artificial Analysis's aggregate `mean@5` on 70 challenges, not a result this
per-question pipeline can reconstruct. See `data/manifest.json` for exact IDs,
exclusions, source paths, evaluator descriptions, and snapshot hashes.

## Run evaluations

Run from the repository root. The Fable virtual environment has the native
scorer dependencies used by PHYBench, PRISM, and UGPhysics:

```bash
# Network-free validation of every pre-audit route.
model_evals/fable/.venv/bin/python -m eval pre-audit run \
  --dataset all --model claude-fable-5 --attempts 4 \
  --judge-model gpt-5.6-sol --output eval/artifacts/pre-audit-fable --dry-run

# One-item-per-stage smoke run. Rerun without --max-pending to finish.
model_evals/fable/.venv/bin/python -m eval pre-audit run \
  --dataset all --model claude-fable-5 --attempts 4 \
  --judge-model gpt-5.6-sol --output eval/artifacts/pre-audit-fable \
  --max-pending 1

# Corrected data and the unified HLE-adapted evaluator on all benchmarks.
model_evals/fable/.venv/bin/python -m eval post-audit \
  --dataset all --model claude-fable-5 --attempts 4 \
  --judge-model gpt-5.6-sol --output eval/artifacts/post-audit-fable \
  --max-pending 1
```

Remove `--max-pending 1` and rerun the identical command to resume all pending
work. A completed batch writes top-level `summary.json` with `mean@4` and
`pass@4`; each independent run lives at `BENCHMARK/attempt-N/`. A one-attempt,
one-benchmark post-audit command retains the older flat output layout for
compatibility.

Supported evaluated models are Fable 5, GPT-5.6-Sol/Luna, GPT-6-Astra, Gemini
3.1 Pro Preview, and the configured OpenAI-compatible models. Judges are Sol,
Astra, or Fable and must differ from the evaluated model. Important arguments:

- `--dataset NAME|all`
- `--attempts N` (default 1; use 4 for paper-style metrics)
- `--reasoning-effort low|medium|high|max`
- `--stage prepare|generate|score|summary|all` for pre-audit
- `--stage prepare|generate|judge|summary|all` for post-audit
- `--workers`, `--score-workers` (pre-audit), `--timeout`, and token limits
- `--max-pending N` for bounded smoke/resume work
- `--dry-run` for validation without writes or model calls

Pre-audit inputs can also be exported and externally generated responses can be
scored without using the built-in model backends:

```bash
python3 -m eval pre-audit export --dataset prism --output /tmp/prism.jsonl
python3 -m eval pre-audit evaluate --dataset prism \
  --responses /tmp/responses.jsonl --output /tmp/scores.jsonl --require-all
```

For a custom post-audit-style dataset, use `--data PATH` with JSON, JSONL, or
Parquet rows containing `id`, `question`, and `reference_answer`. `--data`
cannot be combined with `--dataset all`.

## Outputs and resume guarantees

Each attempt records the dataset, selection, configuration/code/prompt hashes,
predictions, judgments or native scores, per-question results, errors, and a
summary. Checkpoints are atomic. References and audit labels are never passed to
the evaluated model. Failed transport/judge calls remain pending and are retried
on the next identical command. A changed dataset, prompt, or configuration
invalidates the run directory instead of mixing results.

## Code map

| Path | Role | Required for fresh runs? |
|---|---|---|
| `__main__.py` | Dispatches `pre-audit` and `post-audit` | Yes |
| `post_audit.py` | Post-audit orchestration and batch aggregation | Yes |
| `datasets.py` | Snapshot validation and normalized data loading | Yes |
| `backends.py` | Model generation and unified HLE-adapted judging | Yes |
| `scoring.py`, `storage.py` | Summaries, fingerprints, atomic checkpoints | Yes |
| `prompts/` | Unified post-audit generation/judge prompts and schema | Yes |
| `pre_audit/pipeline.py` | Original-data API and evaluator routing | Yes |
| `pre_audit/native.py` | Isolated adapters for released rule graders | Yes |
| `pre_audit/runner.py` | Fresh generation, repeated attempts, aggregation | Yes |
| `data/` | Frozen original and corrected inputs plus manifest | Yes |
| `tests/` | Network-free regression tests | Yes for maintenance |
| `reproduction/` | Frozen launchers for specific historical paper experiments | No; reproducibility only |
| `artifacts/` | Paper-matching saved results/provenance | No; evidence only |

The `reproduction` scripts are not the general pipeline and should not be used for a
new arbitrary model/benchmark matrix. They retain exact hard-coded historical
experiment layouts. New work should use the two protocol commands above.

## Tests

```bash
python3 -m unittest discover -s eval/tests -p 'test_*.py'
```

Tests are network-free. Credentials come from the existing provider environment
variables or authenticated Codex CLI and are never stored in manifests.
