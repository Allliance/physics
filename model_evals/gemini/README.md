# Gemini 3.1 Pro evaluation

This suite evaluates `gemini-3.1-pro-preview` without tools, using the benchmark
prediction prompts, dataset selections, reference policies, judges, and
independent-attempt aggregation. The earlier Gemini tool-enabled experiments
were discarded and their result artifacts deleted at the user's request.

| Benchmark | Original questions | Corrected questions | Attempts | Scoring |
|---|---:|---:|---:|---|
| PHYBench | 100 | 88 | 1 | Original EED pass@1; corrected merged Fable High judge |
| PRISM | 100 | 74 | 1 | Original DAG final-answer pass@1; corrected merged Fable High judge |
| UGPhysics | 100 | 78 | 1 | Released rule grader plus Sol High auxiliary equivalence judge; corrected merged Fable High judge |
| HLE Physics | 202 text-only | 115 | 4 | HLE judge; mean@4 and pass@4 |
| CMT | 50 | 49 | 4 | Existing CMT merged Fable High judge; mean@4 and pass@4 |
| CritPt | 55 with references | 54 | 4 | Existing CritPt merged Fable High judge; mean@4 and pass@4 |

The first three default to the same frozen 100-question selections used in the
Sol/Fable corrected comparisons. Every original selected question is retained.
`--scope sol` instead reproduces Sol's larger source runs (100 PHYBench, 833
PRISM, 1,000 UGPhysics); `--scope full` uses 5,520 English UGPhysics questions.
Corrected sets remain the frozen audited subsets in each case.

All six Gemini datasets now run without tools. The suite only accepts
`--tools none`; `repeated/disabled-jobs.json` also prevents the discarded tool
jobs from being restarted from older plans. Saved HLE/CMT no-tools answers and
judgments are reused. CritPt's no-tools condition uses the local 55/54-question
comparison, including
original challenge 00 and excluding unavailable references, rather than the
official server's 70-problem submission format.

For each original response on the first three benchmarks, corrected evaluation
reuses that answer with the corrected reference set and common merged judge.
PHYBench supplies its parsed final answer. HLE also reuses all four original
answers but judges the corrected dataset separately: its exported references
include full rationales, while original HLE uses short reference answers.
CMT and CritPt generate separate original/corrected attempts because their
inputs were edited. Corrected CMT excludes unrepaired question 14, matching the
refreshed Sol comparison. References and audit labels never enter prediction
requests.

## Reasoning and tool settings

All requests use Google's `high` thinking level. CritPt records requested effort
`max` and effective level `high`, because Gemini 3.1 Pro supports low, medium,
and high, with no distinct max setting. Temperature is 1.0 and the maximum
output budget is 65,536 tokens, including thinking. Each request produces one
candidate in an independent context. No lower model is used as a fallback.

No Python execution, search, shell, or file tools are exposed to Gemini in the
active runs. Sol's previous tool-enabled CritPt scores are a different tool
condition and should be labeled accordingly in comparisons.
Judges use Fable High without tools, except original UGPhysics's
released auxiliary stage, which uses Sol High.

Official references: [thinking levels](https://ai.google.dev/gemini-api/docs/thinking),
[model limits](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-pro-preview),
[combined tools](https://ai.google.dev/gemini-api/docs/generate-content/tool-combination).

## Run and resume

```bash
uv venv model_evals/gemini/.venv
uv pip install --python model_evals/gemini/.venv/bin/python \
  -r model_evals/gemini/requirements.txt

# Validate datasets and materialize commands without model calls.
model_evals/gemini/.venv/bin/python model_evals/gemini/run_suite.py \
  --output-dir model_evals/gemini/runs/gemini31-20260908 --stage prepare

# Run independent benchmark jobs concurrently.
model_evals/gemini/.venv/bin/python -u model_evals/gemini/run_suite.py \
  --output-dir model_evals/gemini/runs/gemini31-20260908
```

Set `GOOGLE_API_KEY` or `GEMINI_API_KEY`; the supervisor also accepts an existing
literal assignment in `~/.bashrc` without executing shell code. Fable and Sol
judging use their existing credentials. Secrets are never written to run files.

Rerun the same command to resume completed predictions and judgments. Set
`--workers`, `--repeat-workers`, and `--judge-workers` when preparing a run.
Worker counts may change on resume; attempt and grading settings remain fixed.
Explicit `--judge-max-output-tokens` values in saved repeated-job commands are
preserved on resume. For `gemini31-20260908`, the user increased the CritPt
Fable High judge cap from 8,192 to 32,768 on 2026-09-09 to resolve three
truncated judgments. The migration receipt at
`runs/gemini31-20260908/repeated/judge-budget-increase-32768.json` preserves the
old manifests, pending IDs, and hashes of all predictions and completed grades.
Only those pending judgments use the increased cap; earlier grades retain their
original budget. This is a recorded judge-budget difference from the Sol run.
The supervisor retries incomplete subprocesses at most three
times by default; rerunning continues any remaining work. Changed inputs,
prompts, backend settings, or grader implementations require fresh output paths.

Each run retains raw predictions, model versions, usage, tool events, native
scores, judgments, question selections, hashes, and per-question results.
`commands.json` records every command; `logs/` contains subprocess logs.
The repeated suite records native benchmark output paths. Final scores remain
null until every requested attempt and judgment is resolved.

`mean@4` averages the four binary grades per question and then across questions.
`pass@4` is the fraction of questions solved in at least one of the four
independent attempts. Successful answers are never selectively regenerated.
CritPt preserves Sol's `limit-policy incorrect`; transport and judge failures
remain pending. First-three generation truncations remain pending under their
existing initial-evaluation policy.

Gemini's API timeout is a transport inactivity timeout, not Sol's local session
wall-clock limit. Explicit Gemini token/tool-limit outcomes follow the native
runner's limit policy; transport timeouts remain pending because the provider's
completion state is unknown. Native limit-outcome placeholders retain their
reason but currently omit the partial API payload and usage.

Read current checkpoints without model calls:

```bash
python3 -m model_evals.gemini.status model_evals/gemini/runs/gemini31-20260908 --write
```

This writes `progress.md` and `progress.json` in the run directory. A supervisor
can adopt already running jobs with `--adopt-running`; it verifies each recorded
PID's command/output path before waiting for it and continuing pending stages.

## Verification

### Corrected judge comparison

`rejudge_corrected.py` reuses the frozen corrected Gemini answers from
`runs/gemini31-20260908` and judges them with GPT-5.6-Sol High without tools.
It validates the original prediction, reference, and native judge prompt hashes
before any calls. Fable grades and source artifacts are preserved. The comparison
covers 1,112 outcomes: 88 PHYBench, 74 PRISM, 78 UGPhysics, 460 HLE,
196 CMT, and 216 CritPt. Existing automatic refusal/generation-limit failures
retain their original scoring policy.

```bash
# Validate all inputs without model calls.
model_evals/gemini/.venv/bin/python model_evals/gemini/rejudge_corrected.py --stage prepare

# One-answer smoke check; retains the complete evaluation denominator.
model_evals/gemini/.venv/bin/python model_evals/gemini/rejudge_corrected.py --limit 1

# Run or resume only missing judgments.
model_evals/gemini/.venv/bin/python -u model_evals/gemini/rejudge_corrected.py --workers 24
```

The default output is `runs/sol-rejudge-corrected-20260914/`. It contains
`COMPARISON.md`, `comparison.json`, and `disagreements.csv`, including both judges'
reasoning for every changed label. `inputs.json` freezes exact rendered prompts;
`manifest.json` records source and implementation hashes. `judgments.json`
retains Sol outputs, usage, and transport events. Failed calls stay pending in
`errors.jsonl`; rerunning never repeats successful judgments. A partial smoke
run exits with status 2 because the full evaluation remains incomplete.
Use `--stage summary` to refresh the report without model calls. Changes are
reported in percentage points for pass@1 or mean@4/pass@4, as appropriate.

```bash
python3 -m unittest utils.test_gemini_backend
model_evals/gemini/.venv/bin/python -m unittest discover -s eval/tests
model_evals/gemini/.venv/bin/python -m unittest discover -s model_evals/gemini/tests
```

A one-question actual-data smoke preserves the full initial denominator and
can be resumed in the same directory:

```bash
model_evals/gemini/.venv/bin/python model_evals/gemini/evaluate_initial.py phybench \
  --output model_evals/gemini/runs/smoke-phybench --limit 1
```
