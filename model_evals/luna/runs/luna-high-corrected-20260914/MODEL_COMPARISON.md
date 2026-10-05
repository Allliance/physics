# GPT-5.6-Luna High versus saved GPT-5.6-Sol runs

Both models use Fable 5 High judgments. PHYBench through CMT use High reasoning and no tools for both models. The saved CritPt Sol run used Max reasoning with tools and live web, so that row is contextual rather than a controlled comparison.

| Benchmark | Metric | Luna | Sol | Luna − Sol |
|---|---|---:|---:|---:|
| phybench | pass@1 | 75.00% | 88.64% | -13.64 pp |
| prism | pass@1 | 94.59% | 95.95–97.30% | -2.70 to -1.35 pp |
| ugphysics | pass@1 | 83.33% | 97.44% | -14.10 pp |
| hle | mean@4 | 46.52% | 66.96% | -20.43 pp |
| hle | pass@4 | 66.09% | 78.26% | -12.17 pp |
| cmt | mean@4 | 74.49% | 83.16% | -8.67 pp |
| cmt | pass@4 | 89.80% | 89.80% | +0.00 pp |

For the first three benchmarks, the CSV also includes the later expert audit-credit verdict for each saved Sol answer. Direct Fable scores remain the controlled comparison because Luna has not received that extra credit pass.

See `luna_vs_sol_answers.csv` for the complete side-by-side answer text and per-attempt verdicts.
