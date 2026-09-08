# Paper number reconciliation

Reviewer coverage: **FAIL — 47 singly reviewed problems lack overrides. All 56 conflicts have explicit overrides.**

The 250 processed labels reproduce from 446 submitted reviews and 63 overrides. Exact audit IDs match all initial rejections in the selected exports.

| Dataset | Evaluated | Audited | Problem | Grader | Model | Retained | Audit-derived solved |
|---|---:|---:|---:|---:|---:|---:|---:|
| HLE-Physics | 202 | 98 | 87 | 2 | 9 | 115 | 106 |
| PHYBench | 100 | 56 | 12 | 40 | 4 | 88 | 84 |
| PRISM-Physics | 100 | 74 | 26 | 48 | 0 | 74 | 74 |
| UGPhysics | 100 | 22 | 22 | 0 | 0 | 78 | 78 |

**Totals:** 502 evaluated, 252 initially accepted, 250 rejected; 147 problem errors, 90 grading errors, 13 model errors. After exclusion: 342/355 = 96.34%. All counts are provisional pending reviewer coverage.

## Recomputed saved evaluations

| Run | Questions | Correct attempts / attempts | Solved | Score |
|---|---:|---:|---:|---|
| HLE GPT-5.6-Sol High tools initial | 202 | 382/808 | 113 | mean@4 47.28%; pass@4 55.94% |
| HLE GPT-5.6-Sol High tools corrected | 115 | 361/460 | 105 | mean@4 78.48%; pass@4 91.30% |
| HLE GPT-5.6-Sol High no_tools initial | 202 | 326/808 | 97 | mean@4 40.35%; pass@4 48.02% |
| HLE GPT-5.6-Sol High no_tools corrected | 115 | 308/460 | 90 | mean@4 66.96%; pass@4 78.26% |
| HLE Fable High tools initial | 202 | 380/808 | 108 | mean@4 47.03%; pass@4 53.47% |
| HLE Fable High tools corrected | 115 | 347/460 | 96 | mean@4 75.43%; pass@4 83.48% |
| HLE Fable High no_tools initial | 202 | 360/808 | 107 | mean@4 44.55%; pass@4 52.97% |
| HLE Fable High no_tools corrected | 115 | 329/460 | 94 | mean@4 71.52%; pass@4 81.74% |
| CMT GPT-5.6-Sol High tools initial | 50 | 122/200 | 36 | mean@4 61.00%; pass@4 72.00% |
| CMT GPT-5.6-Sol High tools corrected | 49 | 171/196 | 48 | mean@4 87.24%; pass@4 97.96% |
| CMT GPT-5.6-Sol High no_tools initial | 50 | 95/200 | 28 | mean@4 47.50%; pass@4 56.00% |
| CMT GPT-5.6-Sol High no_tools corrected | 49 | 163/196 | 44 | mean@4 83.16%; pass@4 89.80% |
| CritPt GPT-5.6-Sol Max original | 55 | 185/220 | 49 | mean@4 84.09%; pass@4 89.09% |
| CritPt GPT-5.6-Sol Max corrected | 54 | 189/216 | 51 | mean@4 87.50%; pass@4 94.44% |
| CritPt Fable High original | 55 | 133/220 | 42 | mean@4 60.45%; pass@4 76.36% |
| CritPt Fable High corrected | 54 | 145/216 | 48 | mean@4 67.13%; pass@4 88.89% |
| phybench Fable High | 88 | single attempt | 79 | pass@1 89.77% |
| prism Fable High | 74 | single attempt | 66 | pass@1 89.19% |
| ugphysics Fable High | 78 | single attempt | 66 | pass@1 84.62% |

## Applied corrections and remaining evidence gaps

- Replaced stale appendix totals 132/98/20 and 508/258/376 with 147/90/13 and 502/252/355.
- Removed the unsupported CritPt 55/22/22/0/0 attribution row. CritPt/CMT are outside this processed CSV.
- Separated audit-derived 104/202 → 106/115 HLE estimates from later-run 113/202 → 105/115 scores. All four HLE mean/pass figures reproduce after excluding the current 87 problem-error IDs.
- Corrected CritPt model attribution: 92.59% belongs to Astra (50/54); the Sol Max results used in the table are 94.44% (51/54). Corrected evaluation has 54 challenges, not 55.
- The CritPt ledger covers 59 numbered challenges: 57 final verdicts, two unresolved. The 54-item evaluation omits clean challenge 38 as well as unresolved 11/54 and unrepairable 41/46. Its original-input run adds example 00; it is not an official 55-challenge score.
- Omitted unverified official CritPt initial values 28.60%, 32.30%, and figure value 34.1%. Source API results, settings, and metric are required to reinstate them. Local original-input runs are reported separately, not substituted for official scores.
- Restored PHYBench’s four-attempt GPT audit result as distinct from single-attempt Fable results; selected response exports alone do not establish exact original model snapshots/tool settings. Existing attribution follows manuscript and local workflow descriptions, pending original run manifests.
- Preserved concurrent Fable credit-method updates (79/88, 66/74, 66/78); checked their retained IDs and per-question totals. These differ from plain rejudging (75/88, 64/74, 66/78).
- Corrected sampling description to stratified deterministic selection. The UG parent export has 1,000 rows; PRISM has 833. All 200 printed UG/PRISM sampled IDs match, including order.
- Removed unsupported full-dataset UG percentages and the unverified external system-card numerical comparison from the live appendix; the original text remains in Git history. This check does not verify external literature counts, physics derivations, or quoted expert notes.
- Two-reviewer/override compliance for CMT and CritPt cannot be established by this CSV. Their review workflows are separate; no human review or override was fabricated.
- Fixed generated audit tables/macros to use count-consistent audit fractions, and prevented audit sync from overwriting separate measured figure scores.

Full source hashes, per-run question IDs, and recomputed counts are in paper_numbers.json. Missing reviewer IDs are enumerated by problem in reviewer_coverage.md (reviewer identities themselves are not exported).
