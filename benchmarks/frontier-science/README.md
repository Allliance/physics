# FrontierScience physics evaluation

This directory evaluates the public physics questions in
[`openai/frontierscience`](https://huggingface.co/datasets/openai/frontierscience):
50 Olympiad questions and 20 Research (PhD-level) questions.

The evaluator downloads and filters the source JSONL, generates one answer per question with a
no-tools Codex CLI call, and uses the official paper's judge prompts. Olympiad questions receive a
binary equivalence judgment. Research questions receive 0–10 rubric points and count as successful
at 7 points or higher. Runs append durable JSONL caches and safely resume.

```bash
python3 benchmarks/frontier-science/evaluate.py \
  --model gpt-5.6-sol --reasoning-effort high \
  --judge-model gpt-5.6-sol --judge-reasoning-effort high
```

Use `--limit 1` for a smoke test. Results are written to
`artifacts/gpt-5.6-sol-high/` by default. The paper's headline metrics average Olympiad over 20
independent trials and Research over 30; this local run uses one trial per question unless repeated
externally.

The paper originally used GPT-5-high as its judge. That legacy model is unavailable through the
current Codex endpoint, so this run uses GPT-5.6-sol-high with the exact published grading policy.

For sequential best-of-five evaluation, reusing the completed single-pass run as round 1 and
dropping successful problems before every later round:

```bash
python3 benchmarks/frontier-science/scripts/evaluate_retries.py --rounds 5
```
