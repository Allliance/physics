# CMT evaluation results

Evaluated on September 6, 2026: **GPT-5.6-Sol High**, judged by **Fable 5 High**.
Each problem received four independent attempts, with no feedback between
attempts. Each dataset was scored against its own reference solutions; judges
used no tools.

| Dataset | Problems | Initial mean@4, no tools | Initial mean@4, tools | Pass@4, tools |
| --- | ---: | ---: | ---: | ---: |
| **Clean, after exclusions** | **49** | **83.16%** (163/196) | **87.24%** (171/196) | **97.96%** (48/49) |
| Original | 50 | 47.50% (95/200) | 61.00% (122/200) | 72.00% (36/50) |

**Mean@4** averages correctness over all four attempts per problem.
**Pass@4** counts a problem as solved if at least one of the same four
tool-enabled attempts is correct.

Tools included live web search and computation, with search encouraged. The
model chose when to use them: web search occurred in 58/196 retained Clean
attempts and 85/200 Original attempts.

**Updated audit breakdown (50 problems):** 30 problems (**60%**) were marked
faulty: 29 were repaired and 1 is excluded as unrepairable.

| Audit category | Meaning | Problems | Share |
| --- | --- | ---: | ---: |
| Clean | Problem and reference are good; no repair needed (`green`, `unchanged`). | 20 | 40% |
| Repairable | Faulty problem or reference was corrected; the repaired version is used (`red`, `corrected`). | 29 | 58% |
| Unrepairable | Faulty problem retained without repair and excluded (`red`, `original_retained`). | 1 | 2% |
| **Total** | | **50** | **100%** |

Problems **20, 21, 25, 30, 33, and 49** are now classified as clean. None remain
pending review. The evaluated **49-problem Clean dataset** therefore contains
20 clean and 29 repaired problems.

**Clean exclusions:** remove problems with both `audit_status = red` **and**
`correction_state = original_retained`, designated faulty and not repairable.
Only the following dataset index is excluded from all Clean metrics above:

| Index | Type | Recorded audit issues |
| ---: | --- | --- |
| 14 | ED | Inconsistent answer choices and ambiguous level-spacing definition. |

**Clean refresh:** problem **18** changed its prompt and reference solution.
It received four fresh attempts per condition, judged by Fable 5 High. The
remaining 48 included problems reuse their saved predictions and judgments,
after verifying that prompts, references, and evaluation settings match.
Scores were then recomputed with the updated exclusion list. All reported
scores have complete judgments.

**Historical initial results are unchanged.** Before filtering or this dataset
update, the 50-problem Clean scores were **79.50%**, **85.00%**, and **96.00%**,
respectively. The Original row retains its existing 50-problem results.

Artifacts (gitignored): [original comparison](artifacts/mean-pass-at4-20260906/comparison.json),
[refreshed Clean scores and provenance](artifacts/clean-refresh-20260906/comparison.json),
and [current exclusion IDs](artifacts/clean-refresh-20260906/excluded_ids.json).
