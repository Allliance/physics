# Qwen model evaluations

This directory owns the Qwen and Qwen3.5 evaluation workflows that were
previously mixed into `audit/`.

- `evaluate_filtered.py` generates and scores PRISM and UGPhysics responses.
- `review_filtered_failures.py` reviews every native rule-grader non-pass.
- `score_prism_parallel.py` runs the released PRISM grader with hard worker
  timeouts.
- `jobs/` contains the full-node vLLM launch and GPU-reset scripts.
- `runs/` contains persisted responses, scores, manifests, audits, server
  metadata, and the consolidated `qwen3_family_summary.json`.
- `logs/` contains Slurm logs from historical Qwen runs.

The filtered evaluations intentionally read reference verdicts from
`audit/initial_data/all-responses/`. They exclude rows whose older reference verdict is
`benchmark_failure`, but the generated model artifacts belong here rather than
under `audit/`.

PHYBench model responses remain under `benchmarks/phybench/artifacts/`, next to
the benchmark's released EED scorer and other PHYBench-native artifacts.
