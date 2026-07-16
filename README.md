# Physics Evaluation

Evaluation and training of LLMs on university-level physics problems.

## Signifiance

For **GPT-5.5-High** as both the generator and judge on the Physics test split
in **merged judge mode**, four cached in-repo runs produced:

| Run | Score |
| --- | ---: |
| 1 | 84.53% |
| 2 | 82.27% |
| 3 | 83.29% |
| 4 | 82.22% |

Aggregating the four runs over rows with all four scores:

| Metric | Score |
| --- | ---: |
| mean@4 | 83.25% |
| best@4 | 89.59% |


## Judge

### Consistency Across Models

Bottom Line: Gemini scores slightly higher, most of the time correctly identifying reference solution typos.

Holding the generator fixed at **GPT-5.5 (high reasoning)**, the merged-mode
judge score changes noticeably between GPT-5.5 and Gemini 3.1 Pro Preview, both
run with high reasoning:

| Dataset | GPT-5.5 judge | Gemini 3.1 Pro Preview judge | Difference |
| --- | ---: | ---: | ---: |
| Physics | 84.53% | 90.04% | +5.51 pts |
| Frontier Physics | 92.00% | 95.70% | +3.70 pts |

Manual review of the merged-mode disagreements found:

- Gemini was more accurate at extracting the parts requested by the finalized
  question text; GPT-5.5 sometimes inferred extra parts from the reference
  solution and penalized answers for omissions that were not actually asked.
- Gemini was often able to identify errors or typos in the reference solutions,
  accepting correct answers that GPT-5.5 rejected because they disagreed with
  the provided reference.
- Despite the score gap, the judges agreed exactly on most merged row scores:
  106/121 Physics rows (87.6%) and 98/110 Frontier Physics rows (89.1%).
  On comparable inferred parts, agreement was higher: 254/267 Physics parts
  (95.1%) and 339/349 Frontier Physics parts (97.1%).
- After aligning GPT-5.5 to Gemini's extracted parts, GPT-5.5 rose to 85.80% on
  Physics and 93.14% on Frontier Physics, but Gemini still led by 4.16 and 2.56
  percentage points respectively.

### Judge modes

The evaluator supports two judge modes. In **separated mode**, the generator is
asked to box one answer per detected problem part, and the judge scores each
extracted part answer against the corresponding ground truth. In **merged
mode**, the generator produces one final boxed answer, and the judge compares it
against the reference solution while inferring the relevant parts.

Merged mode is preferred for headline reporting because separated mode can
produce false negatives when boxed-answer extraction fails, finds the wrong
number of boxes, or maps boxes to the wrong parts. On GPT-5.5 judged by GPT-5.5,
merged mode is only slightly higher than separated mode, consistent with this
mainly reflecting separated-mode extraction false negatives rather than a large
change in model behavior.

| Dataset | Separated | Merged | Difference |
| --- | ---: | ---: | ---: |
| Physics | 83.36% | 84.53% | +1.17 pts |
| Frontier Physics | 89.52% | 92.00% | +2.49 pts |

### Human evaluation

For human inspection, 10 representative samples from Physics and 10 from
Frontier Physics were judged with merged mode. These samples should be reviewed
by expert physicists:

- [PDF review packet](eval/review/gpt-5.5_merged_random_review.pdf)
- [HTML review packet](eval/review/gpt-5.5_merged_random_review.html)

### Self Consistency (GPT-5.5)

GPT-5.5 was judged four times on the same cached GPT-5.5 Physics test
generations in merged mode. The mean scores were stable, with a 0.94 percentage
point standard deviation and a 2.31 point range across runs. Among rows scored
in all four runs, 83.5% received identical scores every time, indicating that
the judge is self-consistent.

For Physics judged in merged mode, the four scores on those same generations
were:

| Run | Score |
| --- | ---: |
| 1 | 84.53% |
| 2 | 82.27% |
| 3 | 83.29% |
| 4 | 82.22% |

### Judge comparison for GPT-5.5 (high)

This table holds the generator fixed at **GPT-5.5 (high reasoning)** and reports
its mean per-problem score from different judges in separated mode.

| Judge | Physics | Frontier Physics |
| --- | ---: | ---: |
| GPT-4.1 | **87.17%** | 85.76% |
| GPT-5.5 (high) | 84.18% | **88.63%** |
| GPT-5 | 81.31% | 86.35% |
| Qwen3.5-35B-A3B (high) | 76.69% | 83.29% |
| GPT-OSS-120B (high) | 76.57% | 85.58% |
| GPT-4o Mini | 52.77% | 56.62% |

Scores exclude failed judge calls. The GPT-5 aggregate uses high-reasoning
judgments when available and low-reasoning judgments as fallback, completing
120/122 Physics and 108/110 Frontier Physics judgments. GPT-OSS-120B completed
119/122 and 107/110. All other judges completed every scorable problem.


## Model results

The table below reports the mean per-problem score on the test splits. All runs use
**separated mode**, in which each problem part is answered and judged separately,
and **GPT-5.5 (high reasoning)** as the judge. Higher is better.

| Model | Physics | Frontier Physics |
| --- | ---: | ---: |
| GPT-5.5 (high) | **84.18%** | **88.63%** |
| Gemini 3.1 Pro Preview | 78.55% | 82.69% |
| Qwen3.5-35B-A3B (high) | 69.84% | 68.09% |
| GPT-OSS-120B (high) | 68.44% | 62.61% |
| Qwen3.5-9B (high) | 64.86% | 55.21% |
| Qwen3.5-4B | 52.51% | 48.06% |
| GPT-4o | 38.01% | 39.82% |
| GPT-4o Mini | 27.30% | 26.52% |

Physics contains 122 scored problems (one additional problem has no ground-truth
parts), while Frontier Physics contains 110. The Qwen3.5-4B run omitted one failed
generation in each dataset and is therefore scored on 121 and 109 problems,
respectively.
