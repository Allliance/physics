# Main audit results

Fresh **2026-09-23 canonical-prompt results**, using **GPT-5.6-Sol High** through ordinary Codex with shell/network tools and live web search enabled. See [ABA_RESULTS.md](ABA_RESULTS.md) for the same-settings comparison with three-case and ABA and all three pooled scores.

Exact [canonical audit prompt](prompt_candidates/canonical_codex_tools_problem_answer.txt). HLE labels use `problem_verify == 0 or answer_verify == 0`; rationale-only defects are clean. HLE retains the four subjects below, excluding Physics, Engineering, Humanities/Social Science, Other, Uncertain, and image-dependent items. Our constructed physics set retains its original expert labels.

## Our constructed audit dataset

| Benchmark / subject | Items | Faulty | Clean | Precision | Recall | Accuracy |
|---|---|---|---|---|---|---|
| CMT | 50 | 30 | 20 | 85.19% | 76.67% | 78.00% |
| CritPt | 54 | 19 | 35 | 33.33% | 36.84% | 51.85% |
| HLE Physics | 98 | 86 | 12 | 97.56% | 93.02% | 91.84% |
| PHYBench | 56 | 13 | 43 | 62.50% | 76.92% | 83.93% |
| PRISM | 74 | 26 | 48 | 77.42% | 92.31% | 87.84% |
| UGPhysics | 22 | 18 | 4 | 84.21% | 88.89% | 77.27% |
| **Overall** | 354 | 192 | 162 | 81.63% | 83.33% | 80.79% |

## HLE-Verified

| Benchmark / subject | Items | Faulty | Clean | Precision | Recall | Accuracy |
|---|---|---|---|---|---|---|
| Biology/Medicine | 202 | 101 | 101 | 64.71% | 65.35% | 64.85% |
| Chemistry | 63 | 30 | 33 | 60.00% | 60.00% | 61.90% |
| Computer Science/AI | 158 | 45 | 113 | 40.98% | 55.56% | 64.56% |
| Math | 834 | 336 | 498 | 70.30% | 69.05% | 75.78% |
| **Overall** | 1257 | 512 | 745 | 65.20% | 66.60% | 71.92% |

## Combined

| Dataset | Items | Faulty | Clean | Precision | Recall | Accuracy |
|---|---|---|---|---|---|---|
| Combined | 1611 | 704 | 907 | 69.68% | 71.16% | 73.87% |

Combined metrics pool individual items from both datasets; the physics labels retain their source-specific scopes.

All 1,611 predictions are fresh model responses. Accuracy includes every item; there are no abstentions or fallback labels. [Metrics](../scratch/auto-audit/all-methods-codex-tools/results/metrics.json) and [independent validation](../scratch/auto-audit/all-methods-codex-tools/results/validation.json).
