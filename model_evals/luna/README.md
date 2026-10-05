# GPT-5.6-Luna evaluations

## Pre-audit protocol

For new Luna pre-audit runs, use four independent attempts and run independent
benchmarks concurrently. HLE-Physics, CMT, and CritPt use **Max reasoning with
tools enabled**, including computation and live web search. PHYBench, PRISM,
and UGPhysics use High reasoning without tools. Fable 5 High judges without
tools where the original benchmark evaluator requires an LLM judge.

The active 2026-09-23 run is documented in
[`scratch/luna-pre-audit-parallel-20260923/README.md`](../../scratch/luna-pre-audit-parallel-20260923/README.md).
It preserves existing High/no-tools PHYBench and PRISM checkpoints. Earlier
High/no-tools HLE results are retained separately and are not part of the
Max/tools result. Original snapshots and native pre-audit graders are retained.

## Historical corrected evaluations

This suite evaluates GPT-5.6-Luna High without tools on the frozen corrected
physics evaluations, judged by Fable 5 High without tools. It uses pass@1 for
PHYBench, PRISM, and UGPhysics, then four independent attempts with mean@4 and
pass@4 for HLE, CMT, and CritPt.

The first three inputs come from Gemini's saved corrected `dataset.json` files,
so later audit edits cannot change their denominators or references. HLE uses
the same saved 115-row corrected export; CMT uses the same frozen 49 IDs; CritPt
validates its audited corrected export before running.
The local snapshots use private dataset identifiers so the unified loader does
not reapply current audit labels to already frozen corrected rows.

Benchmarks run sequentially in this fixed order: PHYBench, PRISM, UGPhysics,
HLE, CMT, CritPt. A later benchmark never starts until the previous benchmark
has a complete score. The runner resumes existing prediction and judgment
checkpoints and retries incomplete invocations without repeating saved work.

```bash
# Validate the plan after the Gemini Sol re-judging comparison is complete.
model_evals/gemini/.venv/bin/python model_evals/luna/run_corrected_suite.py --stage prepare

# Run or resume the ordered suite.
model_evals/gemini/.venv/bin/python -u model_evals/luna/run_corrected_suite.py --workers 24

# Refresh the report without model calls.
model_evals/gemini/.venv/bin/python model_evals/luna/run_corrected_suite.py --stage summary

# Compare completed Luna answers with the saved Sol solver runs.
model_evals/gemini/.venv/bin/python model_evals/luna/compare_with_sol.py
```

The default run directory is `runs/luna-high-corrected-20260914/`. Its
`RESULTS.md` and `summary.json` track the ordered suite, while native HLE, CMT,
and CritPt artifacts remain under each benchmark's documented artifact tree.
`MODEL_COMPARISON.md` summarizes Luna versus Sol, and
`luna_vs_sol_answers.csv` contains their full answers side by side. The saved
CritPt Sol baseline used Max reasoning with tools, so its row is labeled as a
contextual comparison rather than the same High/no-tools protocol.
