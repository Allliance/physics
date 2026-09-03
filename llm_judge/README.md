# LLM judge experiments

`meta_evaluation_dataset.jsonl` is a deterministic sample of up to 100 eligible
rows from each dataset in `audit/all-responses/`.

A row is ineligible only when `AI_audit.verdict` is `benchmark_failure` or
`problem_failure`. Rows without an `AI_audit` field remain eligible. Every
selected row retains all fields from its source row and adds:

- `meta_eval_id`: stable dataset/index identifier;
- `dataset`: source dataset name;
- `source_path`: repository-relative source JSONL path;
- `source_index`: zero-based row index in the source JSONL;
- `source_line_number`: one-based source JSONL line number;
- `final_grade`: audit-corrected binary outcome, where `1` means the model
  solved the problem and `0` means it did not.

`final_grade` is `1` for `grader_failure`, `0` for `model_failure`, and falls
back to `rule_based_binary_score` when `AI_audit` is absent. Rows with an
excluded audit verdict do not receive a grade because they are not selected.

The manifest records input and output hashes, eligibility counts, the exact
selected indices and problem IDs, and the selection method used to construct
this dataset.

## Running judge evaluations

The evaluator gives each model the problem, reference solution, and candidate
response, but never exposes `final_grade` or `AI_audit`. It expects one holistic
binary grade and compares it with `final_grade`.

Run a small Codex smoke evaluation:

```bash
python3 -m llm_judge.eval --backend codex --model gpt-5.5 --limit 5
```

Run against an OpenAI-compatible endpoint:

```bash
python3 -m llm_judge.eval \
  --backend openai \
  --model my-judge-model \
  --base-url http://localhost:8000/v1 \
  --max-workers 32
```

Run through Anthropic's native Messages API. The backend reads
`CLAUDE_API_KEY` (or `ANTHROPIC_API_KEY`) and `ANTHROPIC_BASE_URL` from the
environment unless they are supplied explicitly:

```bash
python3 -m llm_judge.eval \
  --backend anthropic \
  --model "Claude Opus 5" \
  --max-workers 32
```

The Anthropic backend defaults to an 8,192-token completion ceiling because
reasoning models can consume several thousand internal thinking tokens before
emitting the structured judgment.

Use `--prompt strict-reference` to select the alternative prompt in
`prompts.py`, `--dataset prism` to filter rows, and `--dry-run` to inspect the
fully rendered first prompt without making a model call. Run `--help` for all
model and sampling options.

Outputs are resumable JSONL files under the gitignored `judgements/` directory.
Each model/prompt/configuration gets a distinct run ID and adjacent summary JSON
with accuracy, balanced accuracy, class recalls, and a confusion matrix.
