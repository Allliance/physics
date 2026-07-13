# Physics

Evaluation and training of LLMs on university-level physics problems.

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

## Judge comparison for GPT-5.5 (high)

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
