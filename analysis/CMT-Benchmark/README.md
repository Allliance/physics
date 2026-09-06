# CMT evaluation: GPT-5.6-Sol and Fable 5

This pipeline adapts `benchmarks/hle` to the local `data/cmt_data_clean.json`.
It evaluates each complete question in merged mode, judges the final answer,
and aggregates independent attempts. It uses the local dataset as it stands,
including any reviewed corrections; it does not download or overwrite it.

```text
CMT-Benchmark/
├── evaluate.py          # CLI entry point
├── cmt_eval/            # Dataset loader, runner, model backends, and scoring
│   └── prompts/         # CMT prediction/judge prompts and JSON judge schema
├── tests/              # Network-free regression tests
├── data/
│   ├── cmt_data_clean.json  # Evaluation inputs and reference solutions
│   └── cmt_data_original.jsonl # Original Hugging Face dataset, accepted directly
└── artifacts/          # Predictions, judgments, manifests, summaries; gitignored
```

## Run

From this directory, using Python 3.10 or newer:

```bash
python3 -m pip install -r requirements.txt

# All questions, one attempt per question, high effort, no tools.
python3 evaluate.py --model gpt-5.6-sol
python3 evaluate.py --model fable

# Evaluate the original Hugging Face dataset with Sol High and Fable judging.
python3 evaluate.py --dataset data/cmt_data_original.jsonl \
  --model gpt-5.6-sol --reasoning-effort high --judge-model fable \
  --output artifacts/sol-high-original.json

# Three independent attempts, tools enabled, pass at 3.
python3 evaluate.py --model fable --use-tools --rounds 3 --aggregation max \
  --output artifacts/fable-tools-three-rounds.json

# Select by CMT type, or by a JSON list of indices.
python3 evaluate.py --list-categories
python3 evaluate.py --model gpt-5.6-sol --category HF \
  --output artifacts/sol-hf.json
python3 evaluate.py --model fable --ids-file selected.json \
  --exclude-ids-file excluded.json --output artifacts/fable-subset.json
```

Both ID files accept integer indices or digit strings, for example `[0, "1", 2]`.
IDs in outputs are strings. Exclusions take precedence over inclusions and apply
before `--max-samples`. Category filtering uses the row's `type`, ignores case,
and defaults to all types. Unknown requested IDs in the selected category and
empty selections are errors. `--dataset PATH` accepts a JSON array or a `.jsonl`
file containing one object per nonblank line. Both formats require unique
nonnegative integer `index` values and nonempty `prompt`, `solution`, and `type`
strings. The original Hugging Face file already uses these fields, so no
renaming or conversion is needed. The default is `data/cmt_data_clean.json`;
use a separate output path when evaluating the original dataset.

Each prediction receives only the question's `prompt`. Reference `solution`
values go only to the judge; audit notes and other row metadata are excluded.
Prediction prompts follow CMT's single boxed LaTeX answer instructions. The
judge accepts equivalent mathematical expressions and evaluates all requested
components together, with one binary grade and no partial credit. This is an
LLM-judged evaluation following the HLE pipeline, not a reproduction of an
upstream symbolic scoring implementation.

## Models and tools

GPT-5.6-Sol uses `utils/codex_cli` and existing Codex CLI authentication.
Fable 5 without tools uses the Anthropic Messages API; with `--use-tools`, it
uses a fresh Claude Code CLI session. Each attempt starts a fresh conversation.
**Fable judges Sol, and Sol judges Fable.** Both judges default to high effort
and always run without tools. Self-judging is rejected.

Fable requires `ANTHROPIC_AUTH_TOKEN` or `ANTHROPIC_API_KEY`
(`CLAUDE_API_KEY` is also accepted), and optionally `ANTHROPIC_BASE_URL`.
Both backend credentials are needed for a complete run of either model.
The Fable endpoint model ID resolves from `--fable-model`, then
`ANTHROPIC_DEFAULT_FABLE_MODEL`, then the model mapping in Claude
`settings.json` (`CLAUDE_CONFIG_DIR` is honored), then `claude-fable-5`.
Credentials are not stored in artifacts.

Tool sessions use temporary working directories. Sol uses its Codex tools;
Fable permits Bash, Read, Write, Edit, and, when enabled, WebSearch and WebFetch.
Tool traces are saved with predictions. The prompt prohibits looking up local
datasets, reference answers, and previous attempts.

| Option | Default | Meaning |
| --- | --- | --- |
| `--rounds` | `1` | Independent attempts for every selected question. |
| `--aggregation` | `mean` | Per-question mean or maximum across rounds, then average over questions. |
| `--reasoning-effort` | `high` | Prediction effort; `max` is Fable-only. |
| `--judge-reasoning-effort` | `high` | Effort for the other model acting as judge. |
| `--use-tools` | false | Enable tools; `--no-use-tools` explicitly disables them. |
| `--web-search` | conditional | `live` with tools, otherwise `disabled`; Sol also supports `cached`. |
| `--num-workers` | `4` | Concurrent predictions or judgments within a round. |
| `--timeout` | `1800` | Backend request/session timeout in seconds. |
| `--max-output-tokens` | `32768` | Fable-only response budget, including thinking. |
| `--max-tool-turns` | `20` | Fable CLI session turn limit. |
| `--claude-bin` | `claude` | Fable tool-session executable. |
| `--max-samples` | all | Limit after category, inclusion, and exclusion filters. |

## Artifacts and resume

Default dataset and output paths work from any current directory. All outputs
must be under this benchmark's gitignored `artifacts/`. Relative `--output`
paths resolve from this benchmark directory; other explicit input paths resolve
from the current working directory. Use a distinct output path for each
configuration and for simultaneous runs.

For `--output artifacts/run.json`:

- `run.json`, `run.round2.json`, etc. contain predictions keyed by index.
- `run.judged.json`, `run.round2.judged.json`, etc. contain reference answers,
  extracted model answers, judge reasoning, and correctness.
- `run.run.json` and `*.meta.json` contain configuration and input/prompt hashes.
- `run.summary.json` contains mean and max scores, the chosen final score,
  percentages, round scores, and each question's scores across rounds.

Rerun the same command to resume. Completed predictions and judgments are
reused; missing work is retried. Increase `--rounds` to add attempts or change
`--aggregation` to rescore saved judgments without model calls. Reducing rounds
scores only the requested prefix. Worker count and timeout can also change.
Changes to selected prompts, reference solutions, model, effort, tools, judge,
or grading prompts require a new output path. Historical evaluation files
outside `artifacts/` are not imported as checkpoints.

`mean` averages correctness across attempts per question; `max` counts a
question as solved if any attempt is correct (pass at N). For example, two
rounds solving different halves give 50% mean and 100% max. A final score is
reported only once all requested predictions and judgments are present.
Failures yield a nonzero exit status, `complete: false`, and `final_score: null`;
missing results are never dropped from the denominator. Completed refusals are
incorrect; truncated responses, unexpected model substitutions, and malformed
judgments remain pending. Checkpoint writes use atomic file replacement.

## Validation

```bash
# Network-free regression suite.
python3 -B -m unittest discover -s tests -p 'test_*.py'

# Live one-question smoke runs (require both backends' credentials).
python3 evaluate.py --model gpt-5.6-sol --max-samples 1 \
  --output artifacts/smoke-sol.json
python3 evaluate.py --model fable --max-samples 1 \
  --output artifacts/smoke-fable.json
```
