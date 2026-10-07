# Pre-audit protocol

This package pairs the frozen original-data snapshots in `eval/data/pre_audit`
with the evaluator used before audit:

| Dataset | Evaluated rows | Evaluator |
|---|---:|---|
| PHYBench | 100 | released EED; pass iff EED = 100 |
| HLE-Physics | 202 | HLE equivalence judge |
| PRISM-Physics | selected 100 | released final-answer DAG grader |
| UGPhysics | selected 100 | released rule grader, then auxiliary judge |
| CMT-Benchmark | 50 | HLE-adapted equivalence judge |
| CritPt | 55 | HLE-adapted equivalence judge |

The CritPt snapshot archives 71 rows but only 55 have an original reference.
The other 16 are recorded as excluded rather than scored as failures.

CritPt's judge adapter and original prompt/schema are in `critpt.py` and
`prompts/`. It uses the shared no-tool backends and has no dependency on the
analysis folder or historical model runners. Its judge-contract hashes are
recorded in run manifests and checked when resuming.

Fresh repeated evaluation:

```bash
model_evals/fable/.venv/bin/python -m eval pre-audit run \
  --dataset all --model claude-fable-5 --judge-model gpt-5.6-sol \
  --attempts 4 --output eval/artifacts/pre-audit-fable
```

Use `--dry-run` to validate routes without writes or network calls, or
`--max-pending 1` for a bounded smoke run. Rerunning the same command resumes.

The package also supports external generation:

```bash
python3 -m eval pre-audit datasets
python3 -m eval pre-audit export --dataset prism --output /tmp/questions.jsonl
python3 -m eval pre-audit evaluate --dataset prism \
  --responses /tmp/responses.jsonl --output /tmp/results.jsonl --require-all
```

`Problem.prompt` and `Problem.system_prompt` are the original generation inputs;
the reference is excluded from `predictor_input()`. `Problem.native` is retained
privately for native rule graders. Native scorer failures remain retryable errors.
PHYBench responses use `{"final_answer":"..."}`; the other evaluators consume
raw model text.

The PHYBench, PRISM, and UGPhysics graders are loaded directly from unmodified
upstream Git submodules. Initialize them with
`git submodule update --init benchmarks/phybench benchmarks/prism benchmarks/ugphysics`.
The external adapter retains formatting and worker-limit compatibility without
editing upstream files. Run manifests record the upstream commit and source
hashes, so use a fresh output directory after migrating from the archived local
runners. See the parent README for upstream links and archive locations.
