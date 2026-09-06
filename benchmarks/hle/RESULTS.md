# HLE-Physics results

Four attempts per question on 202 text-only questions; all 28 multimodal questions excluded. Corrected results exclude 87 `PROBLEM_FAILURE` questions, leaving 115 questions.

Harnesses: **Codex** for GPT-5.6-Sol with tools; **Claude Code** for Fable 5 with tools. Both models use high reasoning effort. GPT-5.6-Sol High judges Fable 5, and Fable 5 High judges GPT-5.6-Sol; judges use no tools.

| Model | Initial mean@4 | Initial pass@4 | Corrected mean@4 | Corrected pass@4 |
| --- | ---: | ---: | ---: | ---: |
| GPT-5.6-Sol High (no tools) | 40.35% | 48.02% | 66.96% | 78.26% |
| GPT-5.6-Sol High | 47.28% | 55.94% | 78.48% | 91.30% |
| Fable 5 (no tools) | 44.55% | 52.97% | 71.52% | 81.74% |
| Fable 5 | 47.03% | 53.47% | 75.43% | 83.48% |

We audited the 98 problems GPT-5.6-Sol failed to solve in the earlier run used for audit selection. These are the current verdicts in `audit/audits_processed.csv`:

| Audit verdict | Problems |
| --- | ---: |
| Problem failure | 87 (88.78%) |
| Grader failure | 2 (2.04%) |
| Actual model failure | 9 (9.18%) |
| **Total** | **98 (100%)** |
