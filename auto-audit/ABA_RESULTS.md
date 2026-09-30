# Canonical, three-case, and ABA audit results

Completed **2026-09-23**: **4,833 fresh audits**, comprising all three methods on the same 354 physics and 1,257 HLE-Verified items. **GPT-5.6-Sol High** and **ordinary Codex CLI 0.156.0** are used throughout. **Shell, network access, live web search, and page retrieval are enabled for every method.** These results replace the earlier runs with differing tool settings; no earlier predictions or fallback labels are reused.

## Labels and datasets

HLE-Verified uses the same label rule for all three methods:

```python
faulty = (problem_verify == 0) or (answer_verify == 0)
```

Rationale-only defects are clean. All three audit prompts follow this problem/answer fault scope. Original rationale remains available as supporting evidence; if the question itself requests a proof or derivation, that requested answer is assessed. Our constructed physics dataset has no verification-flag columns and retains its original source-specific expert labels across methods.

| Dataset | Items per method | Faulty | Clean |
|---|---:|---:|---:|
| Our constructed physics | 354 | 192 | 162 |
| HLE-Verified | 1,257 | 512 | 745 |
| **Combined** | **1,611** | **704** | **907** |

HLE-Verified retains Biology/Medicine, Chemistry, Computer Science/AI, and Math. Physics, Engineering, Humanities/Social Science, Other, Uncertain, and image-dependent items remain excluded. The constructed physics set retains all six source benchmarks, including its own HLE Physics subset.

## Overall performance

| Dataset | Items | Method | Precision | Recall | Accuracy |
|---|---|---|---|---|---|
| Our physics | 354 | Canonical | 81.63% | 83.33% | 80.79% |
| Our physics | 354 | Three-case | 75.76% | 91.15% | 79.38% |
| Our physics | 354 | ABA | 74.89% | 91.67% | 78.81% |
| HLE-Verified | 1,257 | Canonical | 65.20% | 66.60% | 71.92% |
| HLE-Verified | 1,257 | Three-case | 60.16% | 74.02% | 69.45% |
| HLE-Verified | 1,257 | ABA | 58.70% | 73.83% | 68.18% |
| Combined | 1,611 | Canonical | 69.68% | 71.16% | 73.87% |
| Combined | 1,611 | Three-case | 64.34% | 78.69% | 71.63% |
| Combined | 1,611 | ABA | 63.03% | 78.69% | 70.52% |

## Physics by benchmark

| Benchmark | Items | Faulty | Clean | Method | Precision | Recall | Accuracy |
|---|---|---|---|---|---|---|---|
| CMT | 50 | 30 | 20 | Canonical | 85.19% | 76.67% | 78.00% |
| CMT | 50 | 30 | 20 | Three-case | 74.19% | 76.67% | 70.00% |
| CMT | 50 | 30 | 20 | ABA | 77.42% | 80.00% | 74.00% |
| CritPt | 54 | 19 | 35 | Canonical | 33.33% | 36.84% | 51.85% |
| CritPt | 54 | 19 | 35 | Three-case | 38.71% | 63.16% | 51.85% |
| CritPt | 54 | 19 | 35 | ABA | 40.00% | 63.16% | 53.70% |
| HLE Physics | 98 | 86 | 12 | Canonical | 97.56% | 93.02% | 91.84% |
| HLE Physics | 98 | 86 | 12 | Three-case | 93.41% | 98.84% | 92.86% |
| HLE Physics | 98 | 86 | 12 | ABA | 93.33% | 97.67% | 91.84% |
| PHYBench | 56 | 13 | 43 | Canonical | 62.50% | 76.92% | 83.93% |
| PHYBench | 56 | 13 | 43 | Three-case | 54.55% | 92.31% | 80.36% |
| PHYBench | 56 | 13 | 43 | ABA | 50.00% | 92.31% | 76.79% |
| PRISM | 74 | 26 | 48 | Canonical | 77.42% | 92.31% | 87.84% |
| PRISM | 74 | 26 | 48 | Three-case | 73.53% | 96.15% | 86.49% |
| PRISM | 74 | 26 | 48 | ABA | 66.67% | 100.00% | 82.43% |
| UGPhysics | 22 | 18 | 4 | Canonical | 84.21% | 88.89% | 77.27% |
| UGPhysics | 22 | 18 | 4 | Three-case | 81.82% | 100.00% | 81.82% |
| UGPhysics | 22 | 18 | 4 | ABA | 85.71% | 100.00% | 86.36% |

## HLE-Verified by subject

| Subject | Items | Faulty | Clean | Method | Precision | Recall | Accuracy |
|---|---|---|---|---|---|---|---|
| Biology/Medicine | 202 | 101 | 101 | Canonical | 64.71% | 65.35% | 64.85% |
| Biology/Medicine | 202 | 101 | 101 | Three-case | 60.16% | 76.24% | 62.87% |
| Biology/Medicine | 202 | 101 | 101 | ABA | 59.40% | 78.22% | 62.38% |
| Chemistry | 63 | 30 | 33 | Canonical | 60.00% | 60.00% | 61.90% |
| Chemistry | 63 | 30 | 33 | Three-case | 62.16% | 76.67% | 66.67% |
| Chemistry | 63 | 30 | 33 | ABA | 60.00% | 80.00% | 65.08% |
| Computer Science/AI | 158 | 45 | 113 | Canonical | 40.98% | 55.56% | 64.56% |
| Computer Science/AI | 158 | 45 | 113 | Three-case | 38.10% | 71.11% | 58.86% |
| Computer Science/AI | 158 | 45 | 113 | ABA | 36.26% | 73.33% | 55.70% |
| Math | 834 | 336 | 498 | Canonical | 70.30% | 69.05% | 75.78% |
| Math | 834 | 336 | 498 | Three-case | 64.83% | 73.51% | 73.26% |
| Math | 834 | 336 | 498 | ABA | 63.68% | 72.02% | 72.18% |

## Confusion matrices

| Dataset | Method | TP | FP | TN | FN | Balanced accuracy |
|---|---|---|---|---|---|---|
| Our physics | Canonical | 160 | 36 | 126 | 32 | 80.56% |
| Our physics | Three-case | 175 | 56 | 106 | 17 | 78.29% |
| Our physics | ABA | 176 | 59 | 103 | 16 | 77.62% |
| HLE-Verified | Canonical | 341 | 182 | 563 | 171 | 71.09% |
| HLE-Verified | Three-case | 379 | 251 | 494 | 133 | 70.17% |
| HLE-Verified | ABA | 378 | 266 | 479 | 134 | 69.06% |
| Combined | Canonical | 501 | 218 | 689 | 203 | 73.56% |
| Combined | Three-case | 554 | 307 | 600 | 150 | 72.42% |
| Combined | ABA | 554 | 325 | 582 | 150 | 71.43% |

Faulty is positive. Precision is `TP / (TP + FP)`, recall is `TP / (TP + FN)`, and accuracy is `(TP + TN) / N`. Every item is scored, with **no abstentions, unresolved predictions, or fallback labels**. Combined metrics pool individual items from both datasets; physics retains source-specific labels with different scopes from HLE verification flags.

## Identical Codex settings and prompts

| Method | Prompt | Shell / network | Live web search |
|---|---|---|---|
| Canonical | [Exact audit prompt](prompt_candidates/canonical_codex_tools_problem_answer.txt) | Enabled | Enabled |
| Three-case | [Exact audit prompt](prompt_candidates/three_case_codex_tools_problem_answer.txt) | Enabled | Enabled |
| ABA | [Exact audit prompt](prompt_candidates/aba_codex_tools_problem_answer.txt) | Enabled | Enabled |

All methods use the same stock Codex system instructions, agent loop, model, high reasoning effort, tool permissions, live-web setting, original item inputs, and fresh-session procedure. Only the method's audit rubric and output schema differ. Canonical and three-case return a Boolean verdict and reason; ABA additionally returns structured component checks and findings. Their previous tool prohibitions were removed, and the problem/answer-only fault scope was aligned before this rerun.

```bash
codex --search exec --dangerously-bypass-approvals-and-sandbox \
  --model gpt-5.6-sol -c 'model_reasoning_effort="high"' \
  --json --ephemeral --skip-git-repo-check \
  --cd <fresh-workspace> --output-schema <method-schema> -
```

Each call uses a fresh working directory and an auth-only Codex home with stock configuration. No custom filesystem allowlist, network block, tool-count cap, or model token limit is applied. The model receives original item content without labels, repairs, prior predictions, or reviewer notes, and is instructed not to inspect local evaluation files. Web verification is permitted. The [full protocol](../scratch/auto-audit/all-methods-codex-tools/README.md) links prompt diffs and the successful shell/network/web capability check.

During the first batch, an audit's process-cleanup command killed the coordinator. Recovery preserved 96 completed traces, bringing saved results to 1,358. The remaining calls used a private process namespace to prevent cross-job termination, with the same Codex command, user identity, filesystem access, and network/web capabilities. This operational change applied to all methods; [recovery provenance](../scratch/auto-audit/all-methods-codex-tools/results/coordinator_recovery.json) and validation record which calls used it.

The account's Codex usage limit later interrupted the run at 3,152 saved audits. After access was restored, only unfinished items were retried under the same model, prompts, and tool settings. [Resume provenance](../scratch/auto-audit/all-methods-codex-tools/results/quota_resume.json) and all failed-attempt traces are retained.

## Observed tool use and validation

| Method | Audits | Used tools | Used web | Shell commands | Web tool calls |
|---|---|---|---|---|---|
| Canonical | 1611 | 460 | 335 | 747 | 937 |
| Three-case | 1611 | 569 | 407 | 1052 | 1260 |
| ABA | 1611 | 1405 | 749 | 3151 | 2427 |

Tools are available on every call; the model chooses whether to use them. Counts above report actual tool events in the successful audit traces. Technical retries do not depend on correctness. All 4,833 final predictions and their tool records match completed traces; an independent check verified every input, gold label, command setting, and per-benchmark/per-subject metric.

Saved [metrics](../scratch/auto-audit/all-methods-codex-tools/results/metrics.json), [manifest and exact command](../scratch/auto-audit/all-methods-codex-tools/results/manifest.json), and [independent validation](../scratch/auto-audit/all-methods-codex-tools/results/validation.json).

| Method | Physics predictions | HLE-Verified predictions |
|---|---|---|
| Canonical | [JSONL](../scratch/auto-audit/all-methods-codex-tools/results/canonical/physics/predictions.jsonl) | [JSONL](../scratch/auto-audit/all-methods-codex-tools/results/canonical/hle_verified/predictions.jsonl) |
| Three-case | [JSONL](../scratch/auto-audit/all-methods-codex-tools/results/three_case/physics/predictions.jsonl) | [JSONL](../scratch/auto-audit/all-methods-codex-tools/results/three_case/hle_verified/predictions.jsonl) |
| ABA | [JSONL](../scratch/auto-audit/all-methods-codex-tools/results/aba/physics/predictions.jsonl) | [JSONL](../scratch/auto-audit/all-methods-codex-tools/results/aba/hle_verified/predictions.jsonl) |
