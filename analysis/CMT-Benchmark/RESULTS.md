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
