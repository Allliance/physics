# Physics Human Annotation Analysis

This directory contains expert audits of physics benchmarks. Each completed
analysis separates invalid problems from genuine model failures so that broken
or underspecified questions do not count against model performance.

## Analysis status

| Dataset | Annotated rows | Status | Source |
| --- | ---: | --- | --- |
| CritPt | 59 | Analyzed | [`CritPt/annotations.csv`](CritPt/annotations.csv) |
| CMT-Benchmark | 50 | Analyzed | [`CMT-Benchmark/cmt_data_clean.json`](CMT-Benchmark/cmt_data_clean.json) |
| PHYBench | 61 | Pending | [`PSet-Benchmarks/annotations.csv`](PSet-Benchmarks/annotations.csv) |
| HLE-Physics | 129 | Pending | [`PSet-Benchmarks/annotations.csv`](PSet-Benchmarks/annotations.csv) |
| UGPhysics | 21 | Pending | [`PSet-Benchmarks/annotations.csv`](PSet-Benchmarks/annotations.csv) |
| PRISM | 74 | Pending | [`PSet-Benchmarks/annotations.csv`](PSet-Benchmarks/annotations.csv) |

## CritPt

The CritPt file contains one expert annotation for each of 59 unique challenges.
The `final_grade` verdict was assigned from the problem-quality assessment and
the review of the provided AI solution.

| Final grade | Count | Share of annotated challenges |
| --- | ---: | ---: |
| `correct` | 28 | 47.5% |
| `problem_failure` | 27 | 45.8% |
| `model_failure` | 4 | 6.8% |

After excluding the 27 broken or underspecified problems, 32 challenges remain
evaluable. The AI answer was mostly correct on 28 of them, giving an accuracy of
**87.5% on valid problems**. The four genuine model failures are challenges
`16`, `18`, `58`, and `60`.

The main CritPt issue is problem validity, not model performance. The excluded
questions commonly omit a necessary model, convention, physical parameter, or
requested quantity; some admit multiple valid answers, while others depend on
an unstated conjecture. These cases cannot support a unique fair grade and
should not be included in an evaluation score.

The grades mean:

- `correct`: the problem is gradeable and the provided AI answer is mostly
  correct.
- `problem_failure`: the original problem cannot support a unique fair grade
  and should be excluded.
- `model_failure`: the problem is valid, but the provided AI answer is
  materially incorrect.

`problem_failure` takes precedence when both the prompt and the AI answer have
material issues. This prevents an invalid example from being counted as a model
failure.

CritPt currently has annotations for 59 of its 70 challenge IDs. Challenges
`15`, `21`, `24`, `25`, `27`, `34`, `36`, `37`, `43`, `52`, and `63` are not
covered by this analysis. Because there is only one retained annotation per
challenge, these results do not measure inter-reviewer agreement.

## CMT-Benchmark

Of the 50 audited CMT-Benchmark problems, 42 form the valid, evaluable portion
of the benchmark. The other eight have unresolved problem-quality concerns and
are excluded from the reported model scores.

On the valid benchmark problems, GPT-5.6-Sol High achieved **34/42 (81.0%) at
pass@1**. Retrying only failed problems and stopping each one after its first
successful response raised the result to **40/42 (95.2%) at pass@5**. Six of
the eight initial failures were recovered; indices `17` and `18` remained
incorrect after all five attempts. Algebraically equivalent answers were
accepted during grading.

The complete model responses, per-problem verdicts, and aggregate metrics are
stored in
[`CMT-Benchmark/gpt-5.6-sol-high-reviewed/`](CMT-Benchmark/gpt-5.6-sol-high-reviewed/).

## PHYBench, HLE-Physics, UGPhysics, and PRISM

These four datasets share the human-audit records in
[`PSet-Benchmarks/annotations.csv`](PSet-Benchmarks/annotations.csv).

| Dataset | Annotated rows |
| --- | ---: |
| PHYBench | 61 |
| HLE-Physics | 129 |
| UGPhysics | 21 |
| PRISM | 74 |

> Analysis pending. This section will compare their annotation verdicts,
> problem-failure rates, model-failure rates, and model accuracy after invalid
> problems are excluded.
