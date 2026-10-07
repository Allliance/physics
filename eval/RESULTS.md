# Open Frontier Model Performance

Each result is shown as **pre-audit → post-audit**. Every reported value uses
four independent attempts per question, the unified HLE-adapted merged binary
evaluator, and exact-question reuse between pre-audit and post-audit where
applicable. Values are percentages. The Kimi K3 column uses the tool-assisted
replacement protocol: every incorrect base attempt is retried with Kimi K3 Max
in the Codex harness with local execution and OpenRouter web search enabled.
The Qwen3.8-27B column is an OpenRouter **no-tools** evaluation at `xhigh`
reasoning effort. An em dash indicates that the corresponding evaluation has
not yet been completed.

| Dataset | Metric | Kimi K3 (Max) | GLM-5.3-Flash | Qwen3.8-27B (xhigh) |
|---|---|---:|---:|---:|
| HLE | mean@4 | 47.03% → 73.48% | 31.81% → 51.08% | 24.26% → 38.79% |
|  | pass@4 | 55.45% → 83.48% | 51.49% → 78.45% | 39.11% → 60.34% |
| CMT-Bench | mean@4 | 61.50% → 84.18% | 45.00% → 60.71% | 27.50% → 54.59% |
|  | pass@4 | 80.00% → 93.88% | 66.00% → 77.55% | 44.00% → 73.47% |
| CritPt | mean@4 | 57.27% → 66.67% | 34.55% → 40.28% | 19.55% → 28.24% |
|  | pass@4 | 72.73% → 81.48% | 60.00% → 62.96% | 30.91% → 44.44% |

## Evaluation scope

- Kimi K3: HLE 202 → 115; CMT-Bench 50 → 49; CritPt 55 → 54
- GLM-5.3-Flash: HLE 202 → 116; CMT-Bench 50 → 49; CritPt 55 → 54
- Qwen3.8-27B: HLE 202 → 116; CMT-Bench 50 → 49; CritPt 55 → 54

The GLM run uses max reasoning with Codex-sandboxed code execution, initially
with OpenRouter hosted web search. Of 1,464 original generation checkpoints,
391 were explicit terminal no-answers: 322 exhausted the 131,072-token output budget, 28 exceeded
the 20-turn tool budget, 18 stopped without a final answer, and 23 remained
unanswered after targeted hosted-search and preserved-reasoning recovery. One
additional failed hosted-search attempt was successfully completed by resuming
its preserved reasoning with Codex execution.

The reported GLM scores include the earlier Tavily continuation baseline plus
all 259 completed answers from the corrected local recovery, incorporated on
2026-09-21. These answers received 260 distinct answer/reference judgments with
**gpt-5.6-sol, high reasoning, merged mode**: 153 correct and 107 incorrect.
One answer has different pre/post references. Relative to the previous baseline,
152 unique judgments changed from incorrect to correct; one was already correct.
Every completed recovery replaces its previous answer regardless of correctness.
All 1,464 unique question-attempts remain in the denominators, with four attempts
per question; pass@4 is recomputed from the combined per-question outcomes.

The corrected recovery resumed saved work with local GLM, Codex-sandboxed code,
and Tavily search/open tools, under a 400,000-token cumulative output budget
that includes recorded/estimated historical output and discarded local tails.
Nine attempts without saved work were authorized fresh restarts. The 122
unfinished recovery attempts retain their previous incorrect scores. The 46
unvalidated responses from the earlier local serving configuration and separate
streaming-only recoveries are not added by this update; their previous baseline
checkpoints remain in place. Original checkpoints are preserved.

GLM now exceeds Qwen3.8-27B on mean@4 and pass@4 in all six listed dataset/split
combinations. This is a comparison of the recorded protocols: GLM used tools and
extended recovery budgets, while Qwen used no tools. It does not isolate model
capability at a matched inference budget or reproduce Z.ai's published evaluation.

Combined GLM results:
`scratch/glm-5.3-flash-max-tools-20260918/continuation-local-400000-corrected/combined-results/summary.json`.
Per-answer replacement provenance is in `replacement-audit.json` alongside it.

The Qwen run contains 1,463 real model generations and one explicit
administrative incorrect for CritPt post-audit row 61, attempt 1, recorded at
the user's direction after OpenRouter account-credit exhaustion. No model
output was fabricated for that attempt. Exact pre/post reuse saved 640 model
generation calls and 624 judge calls.
