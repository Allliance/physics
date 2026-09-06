# LLM judge experiments

`meta_evaluation_dataset.jsonl` is a deterministic sample of up to 100 eligible
rows from each dataset in `audit/initial_data/all-responses/`.

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

Use `--dataset prism` to filter rows and `--dry-run` to inspect the fully
rendered first prompt without making a model call. Run `--help` for all model
and sampling options.

Outputs are resumable JSONL files under the gitignored `judgements/` directory.
Each model/prompt/configuration gets a distinct run ID and adjacent summary JSON
with accuracy, balanced accuracy, class recalls, and a confusion matrix.

Use `--sample-size N --sample-seed SEED` for a reproducibly random subset. The
summary records the selection method, seed, and a SHA-256 hash of the selected
IDs; sampled runs also receive a distinct filename suffix.

## Required static tests

Run the network-free regression suite after changing `eval.py`, `prompts.py`,
the meta-evaluation dataset, tests, or the server launcher:

```bash
./llm_judge/static_test.sh
```

It validates the full dataset contract, runs all `llm_judge` unit tests,
syntax-checks the server launcher, and checks a seeded 20-row dry-run selection
against its pinned SHA-256 hash. Parsing the full dataset contract makes no API
calls. `.github/workflows/llm-judge-static.yml` runs this network-free command
automatically on pushes and pull requests that modify `llm_judge/`.

After changing evaluator behavior, also run the soft live regression against a
started four-GPU Qwen server:

```bash
source llm_judge/server_runs/<job-id>/endpoint.env
./llm_judge/static_test.sh --live
```

Live mode judges a reproducibly random 100-row sample with seed `42`. It counts
API and parsing failures as misses and passes at 95% whole-sample agreement with
the audit-corrected grades. This threshold is deliberately soft because model
generation is nondeterministic; investigate a failure rather than assuming
that every percentage-point change is an evaluator regression.

## Four-GPU Qwen judge server

`start_judge_server.sh` submits a four-GPU Slurm job running
`Qwen/Qwen3.5-27B` as four data-parallel vLLM replicas. It uses a collision-safe
port, enables prefix caching and Qwen reasoning parsing, writes endpoint details
under the gitignored `server_runs/<job-id>/` directory, and removes its Docker
container when the job ends. The default context limit is 16,384 tokens, while
the evaluation command caps completions at 6,144 tokens; override the former
with `JUDGE_SERVER_MAX_MODEL_LEN` if needed.

Start the server from the repository root:

```bash
./llm_judge/start_judge_server.sh
```

Self-submission defaults to the Docker-enabled `mi355-gpu-36` host. Set
`JUDGE_SERVER_NODE` to use another configured node.

The command prints the Slurm job ID. Once the corresponding
`server_runs/<job-id>/ready.txt` exists, load `endpoint.env` and run the judge:

```bash
source llm_judge/server_runs/<job-id>/endpoint.env
python3 -m llm_judge.eval \
  --backend openai \
  --model "$OPENAI_MODEL" \
  --base-url "$OPENAI_BASE_URL" \
  --api-key "$OPENAI_API_KEY" \
  --max-workers 100 \
  --max-tokens 6144 \
  --temperature 0.6 \
  --top-p 0.95 \
  --extra-body '{"chat_template_kwargs":{"enable_thinking":true},"thinking_token_budget":4096,"top_k":20,"min_p":0.0}'
```

Stop the server with `scancel <job-id>`.

The four-GPU launcher was validated on 2026-09-03 using 100 concurrent,
thinking-enabled judgments selected with `--sample-size 100 --sample-seed
20260903`. The selection hash was
`c07c94f601b686bdf059bbfda2440f919be74c0ed18a4acaa4f52e3557b4c542`.
After resumable retries, all 100 rows had valid output and 98 agreed with the
audit-corrected grade. The four-GPU and prior eight-GPU runs produced identical
grades on all 100 selected rows. This particular random sample contained only
positive audit-corrected grades, so it validates server equivalence and
positive-class agreement, not negative-class recall.

## Judge agreement results

The table below reports pairwise raw agreement on the meta-evaluation dataset.
Each parenthesized value is the number of matching judgments divided by the
number of rows with valid outputs from both judges. `Benchmark binary score`
means the original `rule_based_binary_score`, before AI-audit corrections.

| | Codex GPT-5.5 | Claude Opus 5 | Qwen3.5-27B (thinking enabled) | Benchmark binary score |
|---|---:|---:|---:|---:|
| **Codex GPT-5.5** | 100% | 99.22% (381/384) | 97.38% (372/382) | 73.18% (281/384) |
| **Claude Opus 5** | 99.22% (381/384) | 100% | 97.64% (373/382) | 72.92% (280/384) |
| **Qwen3.5-27B (thinking enabled)** | 97.38% (372/382) | 97.64% (373/382) | 100% | 72.51% (277/382) |
| **Benchmark binary score** | 73.18% (281/384) | 72.92% (280/384) | 72.51% (277/382) | 100% |

The three LLM judges are unanimous on 371 of their 382 shared valid rows
(97.12%). Their lower agreement with the original benchmark score is expected:
the meta-evaluation dataset deliberately retains audited `grader_failure`
examples, where the original rule-based grader assigned an incorrect score.
The dataset is also highly imbalanced—376 of 384 audit-corrected grades are
positive—so these figures should be considered together with class-balanced
metrics when assessing judge quality.
