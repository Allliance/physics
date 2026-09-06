# CMT evaluation results

Evaluated on September 6, 2026: **GPT-5.6-Sol High**, judged by **Fable 5 High**.
Each problem received four independent attempts, with no feedback between
attempts. Each dataset was scored against its own reference solutions; judges
used no tools.

| Dataset | Problems | Initial mean@4, no tools | Initial mean@4, tools | Pass@4, tools |
| --- | ---: | ---: | ---: | ---: |
| **Clean, after exclusions** | **44** | **81.82%** (144/176) | **85.80%** (151/176) | **97.73%** (43/44) |
| Original | 50 | 47.50% (95/200) | 61.00% (122/200) | 72.00% (36/50) |

**Mean@4** averages correctness over all four attempts per problem.
**Pass@4** counts a problem as solved if at least one of the same four
tool-enabled attempts is correct.

Tools included live web search and computation, with search encouraged. The
model chose when to use them: web search occurred in 49/176 retained Clean
attempts and 85/200 Original attempts.

**Audit breakdown (50 problems):** 35 problems (**70%**) were marked faulty:
29 were repaired and 6 are excluded as unrepairable.

| Audit category | Meaning | Problems | Share |
| --- | --- | ---: | ---: |
| Clean | Problem and reference are good; no repair needed (`green`, `unchanged`). | 14 | 28% |
| Repairable | Faulty problem or reference was corrected; the repaired version is used (`red`, `corrected`). | 29 | 58% |
| Unrepairable | Faulty problem retained without repair and excluded (`red`, `original_retained`). | 6 | 12% |
| Pending review | Audit classification is not finalized (`yellow`, `needs_review`). | 1 | 2% |
| **Total** | | **50** | **100%** |

Problem **49** is pending review and remains included under the current
exclusion rule. Thus, the evaluated **44-problem Clean dataset** contains
14 clean, 29 repaired, and 1 pending-review problem; its name does not mean
that all 44 problems were originally fault-free.

**Clean exclusions:** remove problems with both `audit_status = red` **and**
`correction_state = original_retained`, designated faulty and not repairable.
The following six dataset indices are excluded from all Clean metrics above:

| Index | Type | Recorded audit issues |
| ---: | --- | --- |
| 14 | ED | Inconsistent answer choices and ambiguous level-spacing definition. |
| 20 | ED | Incomplete reference; missing center-of-mass degeneracy convention. |
| 21 | PEPS | Scalar norm confused with the effective norm matrix. |
| 25 | ED | Unrestricted hopping and nonunique ground state invalidate universal claims. |
| 30 | Other | Ambiguous temperature regime; missing classical-limit and transport assumptions. |
| 33 | Other | Ambiguous parameter endpoints and missing lattice assumptions. |

Before these exclusions, the 50-problem Clean scores were **79.50%**, **85.00%**,
and **96.00%**, respectively. The corrected scores reuse the existing judgments,
removing all four attempts for each excluded problem. Original results retain
all 50 problems. All reported scores have complete judgments.

Artifacts (gitignored): [original comparison](artifacts/mean-pass-at4-20260906/comparison.json),
[corrected Clean scores](artifacts/mean-pass-at4-20260906/corrected_clean_comparison.json),
and [exclusion IDs](artifacts/mean-pass-at4-20260906/clean_excluded_ids.json).
