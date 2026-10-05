# Gemini 3.1 Pro — no tools

Updated 2026-09-09T10:21:20.957512+00:00

All predictions and judges use no tools. Fable 5 High judges the corrected sets and HLE/CMT/CritPt. The original first three use native scorers, including Sol High auxiliary judging for UGPhysics.

| Benchmark | Split | Questions | Metric | Score |
|---|---|---:|---|---:|
| phybench | original | 100 | pass@1 | 47.00% |
| phybench | corrected | 88 | pass@1 | 93.18% |
| prism | original | 100 | pass@1 | 25.00% |
| prism | corrected | 74 | pass@1 | 93.24% |
| ugphysics | original | 100 | pass@1 | 79.00% |
| ugphysics | corrected | 78 | pass@1 | 96.15% |
| hle | original | 202 | mean@4 | 40.97% |
| hle | original | 202 | pass@4 | 48.51% |
| hle | corrected | 115 | mean@4 | 65.43% |
| hle | corrected | 115 | pass@4 | 74.78% |
| cmt | original | 50 | mean@4 | 50.50% |
| cmt | original | 50 | pass@4 | 58.00% |
| cmt | corrected | 49 | mean@4 | 78.06% |
| cmt | corrected | 49 | pass@4 | 87.76% |

CritPt: all 436 answers and judgments are complete.

| CritPt split | mean@4 | pass@4 |
|---|---:|---:|
| original | 42.73% | 58.18% |
| corrected | 54.63% | 68.52% |

Three initially truncated CritPt judgments were completed with the user-requested 32,768-token cap (previously 8,192). The judge remained Fable 5 High without tools. All predictions and previously completed grades were preserved; migration and retry verification are recorded under `runs/gemini31-20260908/repeated/`.

The original first-three sets have 100 questions each. Corrected datasets and scorers differ, so original/corrected score differences reflect both changes.
Gemini high thinking is used throughout; CritPt’s requested max is recorded as effective high, the highest supported setting.
