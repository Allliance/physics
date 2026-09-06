# Audit-corrected HLE-Physics

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

Review materials: [question, audit notes, model answers and judge explanations](hle_grader_failure_review.md), [machine-readable corrected results](hle_corrected_evaluation.json), and [excluded IDs](hle_problem_failure_ids.json).

### Reproduction

Run `python3 scratch/hle_corrected_evaluation.py`. The script joins HLE audit labels by `source_problem_id`, removes all four attempts for every excluded question from each condition, recomputes mean@4 and pass@4, and reports grader-failure shares without changing any judgment. It verifies complete four-attempt coverage, saved prediction fingerprints, shared question/reference hashes, and recovery of the original metrics. The audit snapshot and source judgment hashes are saved with the corrected results.
