# Audit label summary

**440 audit records covering 250 distinct problems.** Audit records by benchmark: HLE-Physics 182, PhyBench 100, PRISM 123, UGPhysics 35.

Pass breakdown: **248 first-pass**, **192 second-pass**, **0 third-pass** audits. Of the 250 problems, **190 have two audits** and **60 have one**. Manual overrides resolve **26 conflicts**, including all 18 recently reviewed HLE conflicts; **29 remain unresolved**.

## Labels by benchmark

**Counting rule:** Count each distinct `(dataset, source_problem_id)` once. Retain the existing processed selection and manual overrides; for each remaining unresolved conflict, **use the first-pass label as the tie-breaker**. This tie-breaker applies only to this report and does not mark those conflicts resolved. Rates describe the audited sample, not the full benchmark.

| Benchmark | No. samples included | Problem failure rate | Grader failure rate | Model failure rate |
|---|---:|---:|---:|---:|
| HLE-Physics | 98 | 87.76% | 3.06% | 9.18% |
| PhyBench | 56 | 21.43% | 67.86% | 10.71% |
| PRISM | 74 | 29.73% | 70.27% | 0.00% |
| UGPhysics | 22 | 81.82% | 13.64% | 4.55% |
| **Aggregated** | **250** | **55.20%** | **38.40%** | **6.40%** |

Aggregated counts: **138 problem failures**, **96 grader failures**, **16 model failures**. Aggregate rates are weighted by sample count; percentages are rounded to two decimal places.

## All remaining conflicts

**29 conflicts:** 22 Problem–Grader, 4 Problem–Model, and 3 Grader–Model. By benchmark: HLE-Physics 0, PhyBench 8, PRISM 19, UGPhysics 2.

Every remaining conflict is listed below by its audit **display ID**. The final column groups IDs by the **first-pass label used in the rates above**; these remain provisional choices.

| Benchmark | Conflicting labels | Count | First-pass label retained: audit IDs |
|---|---|---:|---|
| PhyBench | Problem–Grader | 4 | **Problem:** #3, #53; **Grader:** #1, #11 |
| PhyBench | Problem–Model | 2 | **Problem:** #21; **Model:** #56 |
| PhyBench | Grader–Model | 2 | **Grader:** #52; **Model:** #42 |
| PRISM | Problem–Grader | 17 | **Problem:** #61, #63, #68, #89, #102, #110, #111, #128; **Grader:** #76, #88, #90, #94, #96, #99, #103, #106, #112 |
| PRISM | Problem–Model | 1 | **Problem:** #124 |
| PRISM | Grader–Model | 1 | **Grader:** #126 |
| UGPhysics | Problem–Grader | 1 | **Problem:** #143 |
| UGPhysics | Problem–Model | 1 | **Problem:** #137 |

*Sources: `audit/audits.csv`, `audit/audits_processed.csv`, `audit/conflicts.json`, and the applied `audit/audit-overrides.json`. Snapshot: 2026-09-06.*
