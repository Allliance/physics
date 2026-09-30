# Auto-audit dataset and results

This collection contains the human-labeled [audit dataset](dataset.jsonl), this consolidated summary, and the three exact prompts used in the final results. Historical results were consolidated on 2026-09-21; subsequent evaluations are documented below, most recently the fresh three-method Codex run with shell/network and live web tools on 2026-09-23.

For the current canonical prompt's Sol High results, including problem counts and precision, recall, and accuracy for our constructed dataset and a separate HLE-Verified section, see [MAIN_RESULTS.md](MAIN_RESULTS.md).

The [current three-method comparison](ABA_RESULTS.md) contains the fresh canonical, three-case, and ABA results with tools and live web enabled throughout. Older experiments below are retained as history.

## Dataset and labels

`dataset.jsonl` contains **354 unique items: 192 faulty and 162 non-faulty**. Each row has `dataset` (source name), `problem_id` (source-local string ID), `problem`, `reference_solution`, and the Boolean human-derived label `faulty`. All 354 reference solutions are present.

| Source | Items | Faulty | Non-faulty |
| --- | --- | --- | --- |
| CMT | 50 | 30 | 20 |
| CritPt | 54 | 19 | 35 |
| HLE Physics | 98 | 86 | 12 |
| PHYBench | 56 | 13 | 43 |
| PRISM | 74 | 26 | 48 |
| UGPhysics | 22 | 18 | 4 |
| **Total** | **354** | **192** | **162** |

`faulty: true` means benchmark/problem error under the source's audit rules; `false` means non-faulty under those rules. The dataset was constructed as follows:

- HLE Physics, PHYBench, PRISM, and UGPhysics: exactly the 250 items in [audits_processed.csv](../audit/audits_processed.csv), using original inputs from `audit/initial_data/selected/*/responses.jsonl`. Only `PROBLEM_FAILURE` maps to faulty; `GRADER_FAILURE` and `MODEL_FAILURE` map to non-faulty.
- CMT: original items from [cmt_data_original.jsonl](../analysis/CMT-Benchmark/data/cmt_data_original.jsonl), with `audit_status` labels from [cmt_data_clean.json](../analysis/CMT-Benchmark/data/cmt_data_clean.json). `red` maps to faulty and `green` to non-faulty.
- CritPt: 54 IDs selected using [corrected_challenge.jsonl](../analysis/CritPt/corrected_challenge.jsonl), retaining **old problem statements and old reference solutions**. Statements come from [original_challenges.jsonl](../analysis/CritPt/original_challenges.jsonl), labels from [verdicts.json](../analysis/CritPt/verdicts.json), and pre-audit GPT-5.6-Sol solutions from commit `7c3246a` in the sibling `critpt-sol` repository. The `problem` verdict `clean` maps to non-faulty; all other problem verdicts map to faulty. Among the 57 resolved verdicts, IDs 38 (no audited final answer) and 41/46 (unrepairable) were excluded.

These labels have different scopes. `GRADER_FAILURE` and `MODEL_FAILURE` are causes assigned during a human audit, not exhaustive certifications that every part of an item is correct. CritPt labels use only the problem verdict, while the audit prompts also detect reference-solution errors. Some apparent false positives therefore reflect a difference in what the prompt and gold label measure. No labels were changed during consolidation.

The former 609-item dataset included assumed-clean items without explicit human review. Its historical results below are separate from the current 354-item dataset.

## Historical results on the current dataset

Faulty is the positive class. TP/FP/TN/FN mean true positives, false positives, true negatives, and false negatives. Balanced accuracy averages faulty-item recall and non-faulty-item specificity. Except where noted, the auditor received the problem and reference without gold labels, human-review notes, dataset names, or candidate model responses. Tools and web search were disabled.

The binary audit prompts require a JSON object with exactly two fields: `faulty` (Boolean) and `reason` (nonempty string). The abstention experiment below instead returns `decision` (`faulty`, `non_faulty`, or `human_review`) and `reason`. No continuous confidence score was requested, so conventional score-based AUROC is unavailable. Fable's previously reported hard-label AUROC is numerically identical to balanced accuracy.

### Full dataset: 354 items

| Model and prompt | F1 | Precision | Recall | Balanced accuracy | Accuracy | TP / FP / TN / FN |
| --- | --- | --- | --- | --- | --- | --- |
| GPT-5.6-Sol High, canonical | 0.8260 | 0.8238 | 0.8281 | 0.8091 | 0.8107 | 159 / 34 / 128 / 33 |
| GPT-6-Astra xhigh, canonical | 0.7956 | 0.8343 | 0.7604 | 0.7907 | 0.7881 | 146 / 29 / 133 / 46 |
| Fable 5 High, canonical | 0.7212 | 0.8623 | 0.6198 | 0.7513 | 0.7401 | 119 / 19 / 143 / 73 |
| GPT-5.6-Sol High, three-case taxonomy | 0.8192 | 0.7306 | 0.9323 | 0.7624 | 0.7768 | 179 / 66 / 96 / 13 |

**GPT-5.6-Sol High with the canonical prompt has the highest overall F1 and balanced accuracy among these runs.** The three-case prompt finds 20 additional faulty items but creates 32 additional false positives. Astra and Fable have higher precision but lower recall.

Sol and Astra completed all 354 items. Fable returned 348 labels; six missing labels, all gold-faulty CMT items (18, 27, 35, 38, 39, 42), count as incorrect/false negatives. The table uses the final failures-as-incorrect scoring, not the earlier incomplete 347-item snapshot. No Gemini evaluation results were present.

The canonical Sol predictions were retained from the earlier 609-item run for unchanged inputs. Its prompt was selected using that earlier dataset, so the 354-item result is not a fresh, untouched prompt-selection holdout.

### Results by source

| Source | Canonical Sol F1 | Canonical Sol balanced accuracy | Canonical Astra F1 | Canonical Astra balanced accuracy | Three-case Sol balanced accuracy |
| --- | --- | --- | --- | --- | --- |
| CMT | 0.7719 | 0.7417 | 0.7368 | 0.7000 | 0.6750 |
| CritPt | 0.4103 | 0.5391 | 0.1935 | 0.4504 | 0.6353 |
| HLE Physics | 0.9529 | 0.8459 | 0.9012 | 0.7994 | 0.6667 |
| PHYBench | 0.7143 | 0.8265 | 0.7692 | 0.8497 | 0.8104 |
| PRISM | 0.8364 | 0.8798 | 0.8727 | 0.9095 | 0.8542 |
| UGPhysics | 0.8333 | 0.5417 | 0.8333 | 0.5417 | 0.5000 |

The three-case prompt improves balanced accuracy only on CritPt. Canonical Sol's strongest F1 is on HLE Physics; CritPt remains the weakest source. Class imbalance matters: UGPhysics has only four non-faulty items, and the three-case prompt marks every UGPhysics item faulty.

### CritPt experiments

All runs below use GPT-5.6-Sol High. The full CritPt subset contains 54 items: 19 faulty and 35 non-faulty.

| Protocol | Items | F1 | Precision | Recall | Balanced accuracy | Specificity | TP / FP / TN / FN |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Canonical, CritPt portion of full run | 54 | 0.4103 | 0.4000 | 0.4211 | 0.5391 | 0.6571 | 8 / 12 / 23 / 11 |
| Three-case, dedicated CritPt run | 54 | 0.5098 | 0.4062 | 0.6842 | 0.5707 | 0.4571 | 13 / 19 / 16 / 6 |
| Three-case, CritPt portion of fresh full run | 54 | 0.5818 | 0.4444 | 0.8421 | 0.6353 | 0.4286 | 16 / 20 / 15 / 3 |
| Two-stage problem then solution | 54 | 0.4918 | 0.3571 | 0.7895 | 0.5090 | 0.2286 | 15 / 27 / 8 / 4 |
| Human-review-assisted | 54 | 0.6545 | 0.5000 | 0.9474 | 0.7165 | 0.4857 | 18 / 18 / 17 / 1 |
| Four real examples in the prompt | 50 | 0.5283 | 0.3889 | 0.8235 | 0.5784 | 0.3333 | 14 / 22 / 11 / 3 |
| Clean-only, without reviewer comments | 35 | — | — | — | — | 0.3429 | 0 / 23 / 12 / 0 |

The two-stage method first audits the problem alone. A faulty verdict stops the conversation; otherwise the old reference solution is supplied in a second turn. Stage 1 rejects 41 items, including all 27 false positives. Stage 2 adds one true positive. This method does not improve balanced accuracy.

The reviewer-assisted run supplies substantive problem and solution comments from the expert review form, excluding identities, administrative fields, and `final_grade`. It improves agreement with the labels, but comments often reveal the review outcome; these are reviewer-assisted metrics. Five of its 18 false positives have a clean CritPt problem verdict but an incorrect model/solution verdict, illustrating the label-scope mismatch.

The four-shot prompt contains clean example IDs **05 and 23** and faulty example IDs **07 and 67**, with old problems, references, labels, and rationales. These four examples are excluded from scoring, leaving 50 items (17 faulty, 33 non-faulty). The earlier dedicated three-case run on the same 50 items had F1 0.5000, balanced accuracy 0.5651, and TP/FP/TN/FN 12/19/14/5. Four-shot prompting makes small F1 and balanced-accuracy gains while reducing specificity and ordinary accuracy; precision remains low.

The clean-only ablation contains 35 non-faulty items and no positive examples, so specificity is the appropriate metric; F1, recall, and balanced accuracy are not informative here. Adding reviewer comments improves specificity from 0.3429 (12 TN, 23 FP) to 0.4857 (17 TN, 18 FP). These exploratory comparisons include stochastic variation. The dedicated and full-dataset three-case evaluations are separate runs, with four differing CritPt predictions.

## Earlier prompt selection and re-audits

### Historical prompt selection

Prompt selection used the former 609-item dataset, with a deterministic label-stratified development set of 180 items (30 per source; 59 faulty, 121 non-faulty) and a 429-item holdout (135 faulty, 294 non-faulty). Examples in the selected canonical prompt were synthetic; no actual benchmark examples or human explanations were included.

| Split | Prompt | F1 | Precision | Recall | TP / FP / TN / FN |
|---|---|---:|---:|---:|---|
| Development, 180 items | Original baseline | 0.6587 | 0.5093 | 0.9322 | 55 / 53 / 68 / 4 |
| Development, 180 items | Conservative rubric | 0.6929 | 0.6471 | 0.7458 | 44 / 24 / 97 / 15 |
| Development, 180 items | Rubric + synthetic examples | 0.7154 | 0.6875 | 0.7458 | 44 / 20 / 101 / 15 |
| Frozen holdout, 429 items | Original baseline | 0.6377 | 0.4731 | 0.9778 | 132 / 147 / 147 / 3 |
| Frozen holdout, 429 items | Rubric + synthetic examples | 0.7233 | 0.6284 | 0.8519 | 115 / 68 / 226 / 20 |

Rubric plus synthetic examples was selected and frozen before holdout evaluation. Full 609-item F1 was 0.6437 for the original baseline and 0.7211 for the selected prompt. The problem-statement-only diagnostic, which ignores reference-only faults, scored F1 0.5054 and balanced accuracy 0.6411 on the old 609-item dataset. These are historical figures under the older labels; the full 609-item figures include development items.

### Re-auditing the canonical Sol positives

All 193 canonical first-pass positives in the current dataset, including 159 true-positive controls and 34 false positives, had been checked by a claim-aware skeptical reviewer and a blind charitable reviewer from the same model family.

| Decision rule | F1 | Precision | Recall | Balanced accuracy | Accuracy | TP / FP / TN / FN |
|---|---:|---:|---:|---:|---:|---|
| Original one-pass | 0.8260 | 0.8238 | 0.8281 | 0.8091 | 0.8107 | 159 / 34 / 128 / 33 |
| Claim-aware reviewer must agree | 0.8198 | 0.8220 | 0.8177 | 0.8039 | 0.8051 | 157 / 34 / 128 / 35 |
| Blind reviewer must agree | 0.8128 | 0.8352 | 0.7917 | 0.8032 | 0.8023 | 152 / 30 / 132 / 40 |
| Both reviewers must agree | 0.8128 | 0.8352 | 0.7917 | 0.8032 | 0.8023 | 152 / 30 / 132 / 40 |

The 34 false positives comprise 13 `GRADER_FAILURE` items, four `MODEL_FAILURE` items, five CMT green items, and 12 CritPt clean items. The skeptical reviewer retained all 34; the blind reviewer reversed four (`cmt::21`, `cmt::30`, `critpt::33`, `critpt::58`) but also rejected seven true positives. Neither review rule improves overall F1 or balanced accuracy. Model agreement on the other 30 false positives does not establish corrected human labels.

## Abstention experiment

On 2026-09-22, GPT-5.6-Sol High was evaluated on the same 354 original items with a new [conservative abstention prompt](../scratch/auto-audit/retired-prompts/prompt_candidates/conservative_abstention.txt). It preserves the canonical material-fault rubric and prioritizes accurate automatic decisions, then low human-review volume. A `human_review` verdict must identify a specific unresolved issue that could change the decision; no numerical review quota is imposed.

| Prompt | Human review | Precision | Recall | Accuracy | Errors |
|---|---:|---:|---:|---:|---:|
| Canonical binary, historical run | 0 / 354 | 82.38% | 82.81% | 81.07% | 67 |
| Conservative abstention, new run | 0 / 354 | 81.50% | 84.90% | 81.36% | 66 |

**The model never abstained**, so this first version did not demonstrate a benefit from delegation. All 354 calls completed successfully; the new confusion matrix is TP/FP/TN/FN **163/37/125/29**. The model changed 21 verdicts, improving 11 and worsening 10. The accuracy difference is one additional correct item in a single run. The canonical prompt remains unchanged.

The [experiment summary](../scratch/auto-audit/abstention-v1/README.md) contains the per-source breakdown, exact evaluation protocol, predictions, and paired verdict changes. Abstentions would be excluded from automatic-decision metrics and reported through coverage and review rate; runtime failures would remain separate. No human reviews were performed.

### Six-item prompt iteration

On 2026-09-22, two prompt revisions were tested with GPT-5.6-Sol High on six fixed items: three correct and three wrong in the previous abstention run, with one of each from CMT, CritPt, and PHYBench. The first revision added a mandatory evidence check but still did not abstain. The [second revision, v3](../scratch/auto-audit/retired-prompts/prompt_candidates/abstention_convention_gate_v3.txt), requires human review when a verdict depends on an unresolved dispute about an implicit convention or validity range. It met the target in both its first run and a fresh repeat.

| Prompt / run | Previous errors delegated | Previously correct delegated | Previously correct retained correctly | Automatic accuracy | Review rate |
|---|---:|---:|---:|---:|---:|
| Previous v1, same six | 0 / 3 | 0 / 3 | 3 / 3 | 50.00% (3/6) | 0.00% |
| Evidence gate, v2 | 0 / 3 | 0 / 3 | 3 / 3 | 66.67% (4/6) | 0.00% |
| Convention gate, v3 | 1 / 3 | 0 / 3 | 3 / 3 | 80.00% (4/5) | 16.67% |
| Same v3 prompt, fresh repeat | 2 / 3 | 0 / 3 | 3 / 3 | 75.00% (3/4) | 33.33% |

Both v3 runs delegate `cmt::30`; the repeat also delegates `critpt::29`. The first run corrects `phybench::256` but still mislabels `critpt::29`; the repeat mislabels `phybench::256`. All three previously correct decisions remain automatic and correct. Automatic precision/recall are 50.00%/100.00% in both v3 runs, with recall based on only one gold-faulty item. Abstentions are excluded from these automatic metrics, not counted as correct.

This is a deliberately selected development set, including five gold-non-faulty items and one gold-faulty item; all three previous errors are false positives. These results do not estimate full-dataset accuracy or delegation rates. All 18 new calls completed successfully. No human reviews or full-dataset rerun were performed. The [detailed pilot report](../scratch/auto-audit/abstention-pilot-v2/README.md) includes all six outcomes, every iteration, exact prompts, review explanations, metrics, and the frozen selection protocol.

### Full evaluation of convention-gate v3

On 2026-09-22, the exact [second revision selected in the pilot](../scratch/auto-audit/retired-prompts/prompt_candidates/abstention_convention_gate_v3.txt) was evaluated afresh on all **354 items** with **GPT-5.6-Sol High**. All calls completed successfully. The model delegated **21 items (5.93%)**, leaving **333 automatic decisions (94.07% coverage)**.

| Prompt / run | Human review | Precision | Recall | Accuracy | Automatic errors |
|---|---:|---:|---:|---:|---:|
| Canonical binary, historical | 0 / 354 | 82.38% | 82.81% | 81.07% | 67 |
| First abstention v1, historical | 0 / 354 | 81.50% | 84.90% | 81.36% | 66 |
| Convention-gate v3, fresh full run | 21 / 354 | 82.70% | 84.53% | 81.98% | 60 |

Precision, recall, and accuracy for v3 apply only to automatic decisions; abstentions are excluded, not counted as correct. No human reviews were performed.

| Dataset | Total | Automatic | Human review | Review rate | Precision | Recall | Accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|
| CMT | 50 | 45 | 5 | 10.00% | 81.82% | 64.29% | 68.89% |
| CritPt | 54 | 47 | 7 | 12.96% | 43.75% | 43.75% | 61.70% |
| HLE Physics | 98 | 94 | 4 | 4.08% | 95.18% | 96.34% | 92.55% |
| PHYBench | 56 | 53 | 3 | 5.36% | 66.67% | 83.33% | 86.79% |
| PRISM | 74 | 73 | 1 | 1.35% | 77.42% | 92.31% | 87.67% |
| UGPhysics | 22 | 21 | 1 | 4.55% | 83.33% | 88.24% | 76.19% |
| **Overall** | **354** | **333** | **21** | **5.93%** | **82.70%** | **84.53%** | **81.98%** |

The 21 referrals catch **7 of the previous abstention run's 66 errors**, while also referring **14 previously correct items**. On the same 333 automatically decided items, the previous abstention prompt scored **82.28%**, compared with **81.98%** now: six errors were corrected and seven new errors introduced. Relative to the canonical binary run, seven of 67 errors and fourteen correct items are delegated; matched-item accuracy is unchanged at 81.98%, with six automatic errors corrected and six introduced. The higher selective accuracy mainly reflects which items are deferred, rather than improved automatic judgments.

The automatic confusion matrix is **TP/FP/TN/FN = 153/32/120/28**. Delegated gold labels are eleven faulty and ten non-faulty. Excluding the six pilot items, the remaining **348 items** have **20 referrals (5.75%)**, **82.01% automatic accuracy**, **83.06% precision**, and **84.44% recall**. This is one fresh run compared with historical predictions; it is not an independent benchmark or a repeated full-dataset trial.

The [full experiment report](../scratch/auto-audit/abstention-v3/README.md) includes matched comparisons, coverage, all predictions, the human-review queue, source counts, and reproducibility details. The full evaluation uses our constructed dataset, not HLE-Verified.

### HLE-Verified Biology/Medicine: convention-gate v3

The exact v3 prompt was also transferred unchanged to all **202 text-only HLE-Verified Biology/Medicine items (101 faulty, 101 non-faulty)** using GPT-5.6-Sol High. Uncertain and image-dependent items remained excluded. All calls completed successfully. The model delegated **14 items (6.93%)** and made 188 automatic decisions, with **61.61% precision, 71.88% recall, and 62.77% accuracy**; these metrics exclude abstentions.

The canonical prompt achieved **66.34% accuracy on all 202** and **67.02% on the same 188 automatic items**. The fourteen referrals catch six canonical errors but also include eight previously correct items. Among automatic decisions, eight errors were corrected and sixteen introduced. Thus this run does not improve over the canonical Biology/Medicine result. The [HLE-Verified results summary](../scratch/hle-verified/HLE_Verified_RESULTS.md#biologymedicine-second-revision-abstention-prompt) and [full experiment report](../scratch/hle-verified/results/gpt-5.6-sol-high-biology-abstention-v3/REPORT.md) contain the three-prompt comparison, complete metrics, predictions, and review queue.

### HLE-Verified Biology/Medicine with rationale-inclusive labels

The same three prediction sets were rescored after defining an item as faulty if **any of problem, answer, or rationale verification is 0**. This changes 64 clean labels to faulty, yielding **165 faulty and 37 clean items** among the same 202 Biology/Medicine items. Existing model decisions and human-review choices are unchanged; no model rerun was needed.

| Prompt | Human review | Precision | Recall | Accuracy |
|---|---:|---:|---:|---:|
| Canonical | 0 | 88.29% | 59.39% | 60.40% |
| Three-case | 0 | 86.21% | 75.76% | 70.30% |
| Abstention v3 | 14 (6.93%) | 91.07% | 64.97% | 65.43% |

Abstention metrics exclude the fourteen referred items and cover 188 automatic decisions. On those same 188 items, canonical and three-case accuracy are 61.17% and 70.74%, respectively. Under this label rule, three-case has the highest accuracy and recall; abstention has the highest precision. The [updated HLE-Verified table](../scratch/hle-verified/HLE_Verified_RESULTS.md#biologymedicine-relabeling-to-include-rationale-defects) links the derived dataset, revised metrics, and scoring provenance. Earlier HLE-Verified tables retain their stated problem-and-answer-only label rule.

### Full HLE-Verified three-case evaluation with rationale defects

GPT-5.6-Sol High was evaluated with the unchanged three-case prompt on all **1,358 retained HLE-Verified items**, excluding Physics, Uncertain, and image-dependent items. Under the rule that any invalid problem, answer, or rationale makes the item faulty, there are **913 faulty and 445 clean items**. The completed set contains 202 reused Biology/Medicine predictions and 1,156 new model responses, with no abstentions or fallback labels.

| Subject | Items | Faulty | Precision | Recall | Accuracy |
|---|---:|---:|---:|---:|---:|
| Biology/Medicine | 202 | 165 | 86.21% | 75.76% | 70.30% |
| Chemistry | 63 | 56 | 92.86% | 69.64% | 68.25% |
| Computer Science/AI | 158 | 90 | 65.69% | 74.44% | 63.29% |
| Engineering | 13 | 0 | 0.00% | N/A | 7.69% |
| Humanities/Social Science | 52 | 0 | 0.00% | N/A | 55.77% |
| Math | 834 | 602 | 83.92% | 67.61% | 67.27% |
| Other | 36 | 0 | 0.00% | N/A | 50.00% |
| **Overall** | **1,358** | **913** | **77.15%** | **69.88%** | **65.83%** |

The overall confusion matrix is TP/FP/TN/FN **638/189/256/275**. The canonical predictions, rescored under the same labels, achieve 80.47% precision, 52.35% recall, and 59.43% accuracy; that historical comparison includes its one documented user-directed Math fallback. Three-case improves 182 decisions and worsens 95. A rule labeling every item faulty would achieve 67.23% accuracy on this imbalanced set. N/A recall indicates no gold-faulty items in the corresponding subject.

The [updated HLE-Verified results](../scratch/hle-verified/HLE_Verified_RESULTS.md#full-hle-verified-three-case-with-rationale-defects) and [full report](../scratch/hle-verified/results/gpt-5.6-sol-high-three-case-all-components/REPORT.md) link the relabeled dataset, all predictions, exact prompt, metrics, and validation records. The original dataset and historical label versions are preserved.

### Current HLE-Verified three-case results after subject exclusions

Excluding Engineering, Humanities/Social Science, and Other removes 101 gold-clean items. Physics, Uncertain, and image-dependent items remain excluded. The current scope is **1,257 items: 913 faulty and 344 clean**, using the problem/answer/rationale label rule and existing GPT-5.6-Sol High three-case predictions. No new model calls were made; there are no abstentions.

| Subject | Items | Faulty | Clean | Precision | Recall | Accuracy |
|---|---:|---:|---:|---:|---:|---:|
| Biology/Medicine | 202 | 165 | 37 | 86.21% | 75.76% | 70.30% |
| Chemistry | 63 | 56 | 7 | 92.86% | 69.64% | 68.25% |
| Computer Science/AI | 158 | 90 | 68 | 65.69% | 74.44% | 63.29% |
| Math | 834 | 602 | 232 | 83.92% | 67.61% | 67.27% |
| **Overall** | **1,257** | **913** | **344** | **82.43%** | **69.88%** | **67.30%** |

The pooled confusion matrix is TP/FP/TN/FN **638/136/208/275**. Labeling every retained item faulty would achieve **72.63% accuracy**. The [current HLE-Verified results](../scratch/hle-verified/HLE_Verified_RESULTS.md#current-hle-verified-four-subjects-three-case-with-rationale-defects) link the filtered dataset, metrics, and report. The preceding seven-subject table documents the earlier scope.

### Canonical, three-case, and ABA comparison

Completed **2026-09-23**: **4,833 fresh GPT-5.6-Sol High audits** using ordinary Codex with **shell/network tools and live web search enabled for all three methods**. Each method covers the same 354 physics and 1,257 HLE-Verified items. HLE labels and every prompt use problem/answer-only faults; physics retains its original expert labels. There are no abstentions or fallback labels.

| Method | Physics accuracy | HLE-Verified accuracy |
|---|---|---|
| Canonical | 80.79% | 71.92% |
| Three-case | 79.38% | 69.45% |
| ABA | 78.81% | 68.18% |

The [current comparison report](ABA_RESULTS.md#overall-performance) includes precision, recall, accuracy, counts, every physics benchmark and HLE subject, pooled results, observed tool usage, and the exact prompts. These fresh results supersede comparisons that used differing tool settings. Earlier experiment sections above retain their historical settings and results.

## System prompts

Only the three prompts used in the final 2026-09-23 results are kept here. Their
contents match the prompt hashes recorded in the final run manifest. See
[MAIN_RESULTS.md](MAIN_RESULTS.md) for canonical results and
[ABA_RESULTS.md](ABA_RESULTS.md) for the three-method comparison.

| Prompt | Experiment |
|---|---|
| [Canonical, Codex tools, problem/answer only](prompt_candidates/canonical_codex_tools_problem_answer.txt) | Fresh matched-settings run on both datasets; shell/network and live web enabled. |
| [Three-case, Codex tools, problem/answer only](prompt_candidates/three_case_codex_tools_problem_answer.txt) | Fresh matched-settings run on both datasets; shell/network and live web enabled. |
| [ABA, Codex tools, problem/answer only](prompt_candidates/aba_codex_tools_problem_answer.txt) | Fresh matched-settings run on both datasets; shell/network and live web enabled. |

Prompts from superseded experiments are archived locally under
[`scratch/auto-audit/retired-prompts/`](../scratch/auto-audit/retired-prompts/).
The historical sections above retain their original results and link to archived
prompts where applicable.
