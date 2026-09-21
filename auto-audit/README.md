# Auto-audit dataset and results

This collection contains the human-labeled [audit dataset](dataset.jsonl), this consolidated summary, and the system prompts used in the experiments. Results were consolidated on 2026-09-21 from the existing evaluations; no new model calls were made.

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

## Results on the current dataset

Faulty is the positive class. TP/FP/TN/FN mean true positives, false positives, true negatives, and false negatives. Balanced accuracy averages faulty-item recall and non-faulty-item specificity. Except where noted, the auditor received the problem and reference without gold labels, human-review notes, dataset names, or candidate model responses. Tools and web search were disabled.

All prompts require a JSON object with exactly two fields: `faulty` (Boolean) and `reason` (nonempty string). No continuous confidence score was requested, so conventional score-based AUROC is unavailable. Fable's previously reported hard-label AUROC is numerically identical to balanced accuracy.

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

## System prompts

The exact prompt texts are preserved below, including the fully rendered four-shot prompt. The output contract is documented above; no scripts or separate configuration files are required to read these materials.

| Prompt | Experiment |
|---|---|
| [Canonical auditor](auto_audit_system_prompt.txt) | Conservative rubric plus synthetic examples; used by canonical Sol, Astra, and Fable runs. |
| [Three-case fault taxonomy](prompt_candidates/three_case_fault_taxonomy.txt) | Dedicated CritPt and full-dataset runs; distinguishes reference error, convention ambiguity, and invalid problem. |
| [Two-stage problem then solution](prompt_candidates/two_stage_problem_then_solution.txt) | Gated CritPt conversation. |
| [Reviewer-assisted fault taxonomy](prompt_candidates/reviewer_assisted_fault_taxonomy.txt) | CritPt with human reviewer comments. |
| [No-comment ablation](prompt_candidates/review_ablation_no_comments.txt) | Matched clean-only CritPt ablation; distinct from the three-case prompt. |
| [Four-shot CritPt prompt](prompt_candidates/critpt-four-shot-system-prompt.txt) | Complete rendered prompt with all four real examples. |
| [Skeptical positive review](prompt_candidates/skeptical_positive_review.txt) | Claim-aware re-audit of first-pass positives. |
| [Blind charitable re-audit](prompt_candidates/blind_normal_human_reaudit.txt) | Re-audit without the first auditor's allegation. |
| [Original baseline](prompt_candidates/baseline.txt) | Historical prompt-selection baseline. |
| [Conservative rubric](prompt_candidates/conservative_rubric.txt) | Historical rubric-only candidate, without synthetic examples. |
| [Problem-statement-only diagnostic](prompt_candidates/problem_statement_only.txt) | Historical ablation; reference supplied as context, but reference-only errors do not count as faulty. |
