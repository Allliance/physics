# GPT-5.6 Sol High evaluation

This evaluation uses the 999-row aggregate at
`PHYSICS/PHYSICS-textonly/physics_textonly.jsonl`.

## Configuration

- Generator: `gpt-5.6-sol`, high reasoning, through `utils.codex_cli.CodexLLM`
- Symbolic scorer: the supplied `api_evaluation/equation_equivilancy.py`
- Fallback judge: `gpt-5.5`, high reasoning, through Codex CLI
- Fallback scope: only candidate answers not accepted by SymPy
- Metric: mean per-problem fraction of extracted boxed answers that match any
  supplied reference answer, preserving the benchmark's original evaluator

Generation completed for 994 problems. Three calls failed and two calls were
stopped; all five score as zero in the full 999-problem metric. The completed
responses are stored in
`../../audit/all-responses/PHYSICS/gpt-5.6-sol-high.jsonl`.

## Results

| Metric | All 999 problems | 994 completed generations |
| --- | ---: | ---: |
| SymPy | 10.3854% | 10.4376% |
| SymPy + GPT-5.5-High fallback | 43.6675% | 43.8871% |

SymPy fully accepted 92 problems. The Codex fallback judged all 901 eligible
problems using 2,337 pairwise calls, with no failed judge calls.

## Artifacts

- `../../audit/audit-data/PHYSICS/gpt-5.6-sol-high/evaluation.jsonl` contains
  one row per benchmark problem, including the SymPy comparisons and scores,
  generation status, fallback status, stable judgment IDs, and combined score.
- `../../audit/audit-data/PHYSICS/gpt-5.6-sol-high/judgments-gpt-5.5-high.jsonl`
  is the append-only judgment journal. Every call stores the candidate and
  reference answers, exact system and user prompts, raw verdict, parsed verdict,
  full Codex event stream, token usage, attempts, timestamps, and any error.
- `../../audit/audit-data/PHYSICS/gpt-5.6-sol-high/summary.json` contains the
  headline metrics, counts, total judge usage, artifact paths, sizes, line
  counts, and SHA-256 hashes.

## Reproduction

Generate or resume responses:

```bash
python3 benchmarks/physics-original/generate_codex.py --workers 16
```

Run the SymPy pass in an isolated dependency environment:

```bash
uv run \
  --with sympy \
  --with 'antlr4-python3-runtime==4.11.*' \
  --with openai \
  --with python-dotenv \
  python benchmarks/physics-original/evaluate_responses.py --workers 16
```

Run or resume the append-only Codex judge:

```bash
python3 benchmarks/physics-original/judge_codex.py \
  --model gpt-5.5 \
  --reasoning-effort high \
  --workers 16
```
