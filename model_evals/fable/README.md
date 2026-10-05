# Fable 5 initial evaluations

`evaluate_initial.py` evaluates **Fable 5 High, without tools, pass@1** on
the exact 100-question UGPhysics, PRISM, and PHYBench selections under
`audit/initial_data/selected/`. All 100 questions are retained, including
items later flagged by auditors. The selection manifest, question text,
and reference solutions are checked against the original native records.

UGPhysics uses its released prompt and `Judger(strict_extract=True)` with
precision `1e-2`, followed by the released auxiliary equivalence prompt on
non-passes. The auxiliary judge is **GPT-5.6-Sol High**, with no tools.
PRISM uses its released prompt and DAG formula verifier, requiring all
final-answer nodes to match. It does not use an additional LLM judge.
PHYBench uses the original final-answer JSON schema and system prompt,
presentation-only LaTeX normalization, and released EED scorer. Initial
pass@1 counts only answers with EED score 100; it uses no LLM judge.
Native grading errors are recorded as non-passes, matching the existing
initial evaluation runners, and listed explicitly in the summary.

Fable uses the existing HLE Anthropic backend and model mapping, adaptive
thinking, high effort, and a 32,768-token output budget including reasoning.
Requests contain only the benchmark prompt; reference solutions and audit
verdicts are not sent to the answering model. Completed responses are never
regenerated on resume. Refusals are scored; failed or truncated generations
remain pending. Checkpoints reject changed model settings, source data,
prompts, and grader code. Each benchmark runs in its own process because
the upstream projects both define a top-level `utils` module.

Set up an isolated environment:

```sh
uv venv model_evals/fable/.venv
uv pip install --python model_evals/fable/.venv/bin/python -r model_evals/fable/requirements.txt
```

One-question smoke test (resume the same directory for the full run):

```sh
model_evals/fable/.venv/bin/python model_evals/fable/evaluate_initial.py ugphysics --limit 1
model_evals/fable/.venv/bin/python model_evals/fable/evaluate_initial.py prism --limit 1
model_evals/fable/.venv/bin/python model_evals/fable/evaluate_initial.py phybench --limit 1
```

Full evaluations:

```sh
model_evals/fable/.venv/bin/python model_evals/fable/evaluate_initial.py ugphysics
model_evals/fable/.venv/bin/python model_evals/fable/evaluate_initial.py prism
model_evals/fable/.venv/bin/python model_evals/fable/evaluate_initial.py phybench
```

`--stage` permits separate prepare, generate, score, auxiliary, and summary
steps. UGPhysics and PRISM outputs default to `runs/<benchmark>-initial-high-100/`;
PHYBench outputs live in `benchmarks/phybench/artifacts/fable-5-high-initial-100/`.
Outputs include
the frozen sample and prompts, configuration and source hashes, raw API
responses, native scores, auxiliary judgments, errors, and summary.
Incomplete runs do not report a final accuracy. `--limit` bounds pending
work for a smoke test without changing the 100-item selection.

Network-free validation:

```sh
model_evals/fable/.venv/bin/python -m unittest discover -s model_evals/fable/tests -p 'test_*.py'
```
