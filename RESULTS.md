# HLE-Physics initial evaluation results

Evaluated on 202 text-only HLE-Physics questions, excluding all 28 image questions. Each condition uses four independent attempts per question, with no feedback between attempts. Both generation and judging use high reasoning effort. Judges receive no tools.

`mean@4` averages binary correctness across all 808 attempts. `pass@4` is the fraction of 202 questions with at least one correct attempt.

## Fable 5

Judge: GPT-5.6-Sol high. Completed September 6, 2026.

| Metric | Correct / total | Result |
| --- | ---: | ---: |
| No tools mean@4 | 360 / 808 | **44.55%** |
| With tools mean@4 | 380 / 808 | **47.03%** |
| With tools pass@4 | 108 / 202 | **53.47%** |

Tool-enabled attempts had web search, web fetch, shell computation, and file tools available. WebSearch was recorded in 104 of 808 tool-enabled outcomes; tool availability does not imply that every attempt searched. Native search used auxiliary search models. Budget-exhausted outcomes were scored incorrect: 11 without tools and 13 with tools.

See the [run notes](benchmarks/hle/artifacts/fable5-initial-20260906/RUN_NOTES.md) for budgets, auxiliary models, retries, and resource interventions; [machine-readable results](benchmarks/hle/artifacts/fable5-initial-20260906/results.json) and prediction/judgment artifacts are retained alongside them.

## GPT-5.6-Sol high

Judge: Fable 5 high. Completed 2026-09-06.

| Metric | Correct / total | Result |
| --- | ---: | ---: |
| No tools mean@4 | 326 / 808 | **40.35%** |
| With tools mean@4 | 382 / 808 | **47.28%** |
| With tools pass@4 | 113 / 202 | **55.94%** |

Native live web search, shell computation, and file tools were available. Web search was recorded in 329 of 808 tool-enabled outcomes.

The question set and four-attempt scoring protocol match the Fable run. Judge models differ, and backend budgets are not identical: Sol uses the Codex execution budget rather than Fable’s response-token and tool-turn caps.

See the [run notes](benchmarks/hle/artifacts/gpt56sol-high-initial-20260906/RUN_NOTES.md) and [machine-readable results](benchmarks/hle/artifacts/gpt56sol-high-initial-20260906/results.json) for configuration and retained prediction/judgment artifacts.

## Audit-corrected HLE-Physics

Excluded all 86 text-only questions marked `PROBLEM_FAILURE` in `audit/audits_processed.csv`, leaving **116 questions** and **464 attempts per model and condition**. All 28 image questions remain excluded.

The retained subset means questions not flagged `PROBLEM_FAILURE`: 104 are unaudited, and 12 have other audit labels. `GRADER_FAILURE` questions remain included with their existing scores pending manual review.

| Model | No tools mean@4 | With tools mean@4 | With tools pass@4 |
| --- | ---: | ---: | ---: |
| Fable 5 | 329/464 (70.91%) | 347/464 (74.78%) | 96/116 (82.76%) |
| GPT-5.6-Sol high | 308/464 (66.38%) | 361/464 (77.80%) | 105/116 (90.52%) |

Judges are unchanged: GPT-5.6-Sol high judges Fable 5, and Fable 5 high judges GPT-5.6-Sol. These are recalculations of saved judgments; no answers were regenerated or regraded.

### GRADER_FAILURE among unsolved retained questions

Unsolved means zero correct answers across all four attempts in the stated condition. Each denominator includes every unsolved retained question, including unaudited questions; the numerator counts those whose processed audit label is `GRADER_FAILURE`.

| Model | No tools | With tools |
| --- | ---: | ---: |
| Fable 5 | 1/22 (4.55%) | 1/20 (5.00%) |
| GPT-5.6-Sol high | 1/26 (3.85%) | 1/11 (9.09%) |

For questions unsolved by **both** models: no tools: 1/15 (6.67%); with tools: 1/10 (10.00%).

### Manual review

Audit verdicts refer to the previously audited responses. Matching a question ID identifies a review candidate; it does not establish that every current judgment is wrong.

| Audit display ID | Source question ID | Fable correct attempts (no tools / tools) | Sol correct attempts (no tools / tools) |
| --- | --- | ---: | ---: |
| 205 | `672ddd9bff7bf1483f564046` | 0/4 / 0/4 | 0/4 / 0/4 |
| 165 | `670402f0bae67686d8aef3e8` | 1/4 / 1/4 | 3/4 / 3/4 |
| 235 | `6739674739118cf30f5f1075` | 2/4 / 1/4 | 2/4 / 2/4 |

Review materials: [question, audit notes, model answers and judge explanations](audit/reports/hle_grader_failure_review.md), [machine-readable corrected results](audit/reports/hle_corrected_evaluation.json), and [excluded IDs](audit/reports/hle_problem_failure_ids.json).

### Reproduction

Run `python3 scratch/hle_corrected_evaluation.py`. The script joins HLE audit labels by `source_problem_id`, removes all four attempts for every excluded question from each condition, recomputes mean@4 and pass@4, and reports grader-failure shares without changing any judgment. It verifies complete four-attempt coverage, saved prediction fingerprints, shared question/reference hashes, and recovery of the original metrics. The audit snapshot and source judgment hashes are saved with the corrected results.
