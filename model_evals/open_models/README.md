# Open-model evaluations

`run_agentic_hle_smoke.py` is the bounded, resumable tool-use smoke runner for
corrected HLE-Physics. By default it evaluates three questions that were wrong
in all four saved Kimi K3 no-tool attempts, then judges completed answers with
the shared HLE-adapted judge.

The native harness calls OpenRouter Chat Completions directly. OpenRouter runs
hosted web search, while client-side `run_command` calls execute through a
Codex permission profile in a fresh temporary directory. The command sandbox
has no network or repository access, receives no API credentials in its
environment, and can write only to its temporary workspace. A model request is
never retried inside a tool turn: failed work remains pending for an explicit
resume.

```bash
python3 model_evals/open_models/run_agentic_hle_smoke.py \
  --model deepseek/deepseek-v4.1-flash \
  --harness native-openrouter \
  --reasoning-effort max \
  --max-output-tokens 384000 \
  --max-tool-turns 20 \
  --timeout 1800 \
  --output scratch/deepseek-v4.1-flash-native-tools-hle-smoke
```

Set `OPENROUTER_API_KEY` in the environment. Keep smoke outputs under
`scratch/`; the reusable runner and native loop belong in the repository.
Rerunning an identical command resumes missing generations and judgments.
Changing the configuration requires a new output directory so results from
different protocols cannot be mixed.

The older `--harness codex` route remains available for compatibility with the
Codex CLI OpenRouter provider and `agentic-web` preset. Prefer
`native-openrouter` for OpenRouter models because its tool protocol, model
identity, per-turn usage, and hosted web-search counts are recorded directly.
