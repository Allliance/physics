# GLM evaluations

`run_agentic_reuse.py` evaluates `z-ai/glm-5.3-flash` at maximum reasoning on
the HLE, CMT-Bench, and CritPt pre-audit and post-audit snapshots. It provides
OpenRouter hosted web search and local Python/shell execution through the Codex
sandbox.

The runner performs four independent generations for each byte-identical
question in the union of both splits. It then fans each response out to every
matching split row and deduplicates judging only when both question and
reference answer are identical. On the current snapshots this reduces 2,104
generation calls to 1,464 and 2,104 judge calls to 1,480.

```bash
python3 -u model_evals/glm/run_agentic_reuse.py \
  --stage all \
  --generation-workers 100 \
  --judge-workers 100 \
  --output scratch/glm-5.3-flash-max-tools-20260918
```

The stages `prepare`, `generate`, `judge`, and `summary` can be run separately.
Every generation and judgment is an individual atomic JSON checkpoint, so the
same command safely resumes missing work. Model requests are not automatically
retried after indeterminate transport failures. The model receives the full
131,072-token provider completion ceiling; completed truncations and partial
tool loops are preserved under `partial-generations/`.

Keep run artifacts under `scratch/`. Only copy final aggregate values into
`eval/RESULTS.md` after `summary.json` reports `"complete": true`.
