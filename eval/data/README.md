# Evaluation data snapshots

This directory is the sole built-in data source for `eval`. Runtime evaluation
does not reconstruct selections from `audit/`, `benchmarks/`, or `analysis/`.
`manifest.json` records each snapshot's SHA-256 digest, source count, evaluation
count, exclusions, original source, and evaluator policy.

| Benchmark | Pre-audit archived | Pre-audit evaluable | Post-audit evaluated |
|---|---:|---:|---:|
| PHYBench | 100 | 100 | 87 |
| HLE-Physics | 202 | 202 | 116 |
| PRISM-Physics | 100 | 100 | 74 |
| UGPhysics | 100 | 100 | 82 |
| CMT-Benchmark | 50 | 50 | 49 |
| CritPt | 71 | 55 | 54 |

`pre_audit/*.jsonl` preserves the original question, reference, native prompt,
response format, and native scorer row. PRISM and UGPhysics are the frozen
100-question text-only samples; PHYBench is the 100 answer-bearing public rows;
HLE is its 202-question text-only Physics subset. All 71 archived CritPt rows
are present, but 16 have no original reference and are explicitly marked
`MISSING_REFERENCE`, leaving 55 that this local pipeline can grade. The paper's
separately reported CritPt pre-audit number comes from Artificial Analysis on 70
challenges and cannot be reconstructed from per-question public judgments.

`post_audit/*.jsonl` contains only the rows actually evaluated after review.
For PHYBench, HLE, PRISM, and UGPhysics, `PROBLEM_FAILURE` rows are excluded.
CMT contains the repaired/validated data and excludes unrepairable index 14.
CritPt contains the 54 retained rows from the 56 audited challenges and uses
the independently established references.

The snapshot files are inputs, not generated run artifacts. Do not edit them in
place. If the reviewed benchmark is intentionally revised, regenerate the
affected snapshot, update its manifest digest/counts/exclusions, and run the
dataset tests.
