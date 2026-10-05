# Fable 5 High: initial pass@1

Completed 2026-09-08. Each benchmark uses the exact 100 questions in
`audit/initial_data/selected/`, with the original questions and references,
one completed Fable 5 High outcome per question, and no tools. No audit
exclusions, repairs, or manual overrides are applied.

| Benchmark | Questions | Native scorer passes | Auxiliary additions | Initial correct | Initial pass@1 |
|---|---:|---:|---:|---:|---:|
| UGPhysics | 100 | 43 | 33 | 76 | **76.00%** |
| PRISM-Physics | 100 | 17 | — | 17 | **17.00%** |
| PHYBench | 100 | 40 | — | 40 | **40.00%** |

UGPhysics uses its native scorer, followed by the released auxiliary
equivalence prompt with **GPT-5.6-Sol High** and no tools. Of 57 native
non-passes, the auxiliary stage accepts 33 and leaves 24 incorrect. One
of the latter is a completed model refusal (`QuantumMechanics/en/827`);
the upstream answer extractor returns no answer, so no judge request is
made for that item. Thus 57 auxiliary-stage records include 56 actual
judge calls and one extraction failure.

PRISM uses its native DAG formula verifier and counts a question correct
only when every final-answer node matches. No additional LLM judge is
applied to its initial score.

PHYBench uses its original final-answer JSON schema, presentation-only
LaTeX normalization, and native EED scorer. An answer passes only when
its EED score is 100. No LLM judge is used. Mean EED score is **48.18/100**;
the binary initial pass@1 is **40.00%**. The PHYBench run recorded no
request failures, refusals, or answer-format errors.

All 300 outcomes identify `claude-fable-5`, and every question has a native
score. There are no native grading errors and no pending generations,
scores, or auxiliary decisions. Eight interrupted UGPhysics requests and
seven interrupted PRISM requests were retried; completed outcomes were
not regenerated. The one completed refusal was retained as incorrect.

Fable uses adaptive thinking at high effort, with a 32,768-token response
budget including reasoning. Full configuration, source hashes, prompts,
raw API responses, scores, judge reports, and per-question CSVs are saved
under:

- [UGPhysics artifacts](runs/ugphysics-initial-high-100/)
- [PRISM artifacts](runs/prism-initial-high-100/)
- [PHYBench artifacts](../../benchmarks/phybench/artifacts/fable-5-high-initial-100/)
- [Aggregate results and provenance](initial_results.json)

The [runner documentation](README.md) provides setup, smoke-test, and
resume commands. Corrected results reusing these responses are reported in the
[unified evaluator results](../../eval/RESULTS.md).
