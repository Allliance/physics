# Reviewer coverage audit

**FAIL: reviewer coverage is incomplete.**

Distinct reviewers are counted from submitted raw annotations, not processed rows or AI audits.
Every disagreement requires an explicit override, including third-pass resolutions.

| Dataset | Problems | ≥2 reviewers | One reviewer | One + override | Missing override | Conflicts | Conflict overrides missing |
|---|---:|---:|---:|---:|---:|---:|---:|
| hle-physics | 98 | 84 | 14 | 1 | 13 | 24 | 0 |
| phybench | 56 | 47 | 9 | 0 | 9 | 10 | 0 |
| prism | 74 | 51 | 23 | 3 | 20 | 19 | 0 |
| ugphysics | 22 | 14 | 8 | 3 | 5 | 3 | 0 |
| Total | 250 | 196 | 54 | 7 | 47 | 56 | 0 |

## Problems requiring a second review or explicit expert override

| Dataset | Display ID | Source problem ID | Current label | Issue |
|---|---:|---|---|---|
| hle-physics | 166 | `670fe03ef99389b3c7942186` | MODEL_FAILURE | fewer_than_two_reviewers_without_override |
| hle-physics | 170 | `671ec6d8a695a5847b48c39a` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| hle-physics | 185 | `67230d6e736f03c0e4c1adee` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| hle-physics | 186 | `672333955d82e15ca8e37afb` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| hle-physics | 196 | `6728e8d695a162eb76520086` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| hle-physics | 198 | `672a27f5d30d6f5584cde73d` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| hle-physics | 220 | `6735bafad86155d1e57160e7` | MODEL_FAILURE | fewer_than_two_reviewers_without_override |
| hle-physics | 223 | `673704af1c2083e9eaa6d732` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| hle-physics | 226 | `67379aea6c946be458900f3f` | MODEL_FAILURE | fewer_than_two_reviewers_without_override |
| hle-physics | 228 | `67380ecdb808e1bf292d214e` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| hle-physics | 238 | `673b4efb373d154ce855b23b` | MODEL_FAILURE | fewer_than_two_reviewers_without_override |
| hle-physics | 243 | `67440064abafa90f5b9d4da9` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| hle-physics | 247 | `67770f6d9a59b3d9ca3a5f82` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| phybench | 4 | `10` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| phybench | 37 | `115` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| phybench | 39 | `131` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| phybench | 18 | `204` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| phybench | 17 | `206` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| phybench | 7 | `250` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| phybench | 46 | `603` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| phybench | 30 | `636` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| phybench | 34 | `708` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 70 | `02_cleaned_dag:1012` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 71 | `02_cleaned_dag:2021` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 72 | `02_cleaned_dag:2039` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 73 | `02_cleaned_dag:2053` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 74 | `02_cleaned_dag:2055` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 75 | `02_cleaned_dag:2076` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 77 | `02_cleaned_dag:3034` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 78 | `02_cleaned_dag:3038` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 79 | `03_cleaned_dag:2029` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 80 | `04_cleaned_dag:1049` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 83 | `04_cleaned_dag:1139` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 87 | `04_cleaned_dag:2074` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 92 | `04_cleaned_dag:4027` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 93 | `04_cleaned_dag:4030` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 118 | `06_cleaned_dag:4010` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 121 | `06_cleaned_dag:5058` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 122 | `06_cleaned_dag:5060` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 123 | `06_cleaned_dag:6001` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 129 | `06_cleaned_dag:8009` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| prism | 130 | `07_cleaned_dag:1065` | GRADER_FAILURE | fewer_than_two_reviewers_without_override |
| ugphysics | 144 | `AtomicPhysics/en/702` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| ugphysics | 147 | `Electrodynamics/en/100` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| ugphysics | 135 | `QuantumMechanics/en/1002` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| ugphysics | 141 | `QuantumMechanics/en/827` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |
| ugphysics | 151 | `Solid-StatePhysics/en/81` | PROBLEM_FAILURE | fewer_than_two_reviewers_without_override |

Processed rows reproduce from raw reviews and overrides (allowing newline normalization).
The companion JSON records every problem and SHA-256 hashes of the input files.
This checks recorded provenance and coverage; it does not invent reviews or certify the scientific verdicts.
