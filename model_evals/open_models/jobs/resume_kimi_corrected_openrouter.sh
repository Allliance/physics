#!/usr/bin/env bash
set -euo pipefail

repo=/shared/data/home/aa3242/physics
python="$repo/model_evals/gemini/.venv/bin/python"
bashrc=/shared/data/home/aa3242/.bashrc
run="$repo/model_evals/kimi/runs/kimi-k3-max-no-tools-20260917/hle-corrected"
cd "$repo"

# Load only the OpenRouter assignment; sourcing the full interactive bashrc can
# terminate a non-interactive batch shell before reaching the key definition.
source <(sed -n '/^[[:space:]]*export[[:space:]]\+OPENROUTER_API_KEY[[:space:]]*=/p' "$bashrc" | tail -n 1)
: "${OPENROUTER_API_KEY:?OPENROUTER_API_KEY is missing from $bashrc}"
export OPENROUTER_PROVIDER_SORT=throughput
export OPENROUTER_APP_TITLE="Physics LLM Evaluation"

"$python" - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path

root = Path("model_evals/kimi/runs/kimi-k3-max-no-tools-20260917/hle-corrected")
counts = {"phybench": 88, "prism": 74, "ugphysics": 78, "hle": 115, "cmt": 49, "critpt": 54}
attempts = {}
for benchmark, count in counts.items():
    for attempt in range(1, 5):
        directory = root / benchmark / f"attempt-{attempt}"
        predictions_path = directory / "predictions.json"
        predictions = json.loads(predictions_path.read_text()) if predictions_path.exists() else {}
        dataset = json.loads((directory / "dataset.json").read_text())
        ids = [str(row["id"]) for row in dataset]
        attempts[f"{benchmark}/attempt-{attempt}"] = {
            "local_prediction_ids": [qid for qid in ids if qid in predictions],
            "openrouter_pending_ids": [qid for qid in ids if qid not in predictions],
            "expected_count": count,
        }
report = {
    "created_at": datetime.now(timezone.utc).isoformat(),
    "conceptual_model": "moonshotai/Kimi-K3",
    "original_route": "local vLLM on mi355-gpu-35",
    "resume_route": "https://openrouter.ai/api/v1 / moonshotai/kimi-k3",
    "provider_sort": "throughput",
    "reason": "User-requested transition from local GPU inference to OpenRouter",
    "attempts": attempts,
}
temporary = root / "provider-transition.json.tmp"
temporary.write_text(json.dumps(report, indent=2) + "\n")
temporary.replace(root / "provider-transition.json")
PY

exec "$python" -u model_evals/open_models/run_corrected_hle.py \
    --model kimi-k3 \
    --benchmarks phybench prism ugphysics hle cmt critpt \
    --base-url https://openrouter.ai/api/v1 \
    --served-model moonshotai/kimi-k3 \
    --manifest-base-url http://127.0.0.1:8000/v1 \
    --manifest-model moonshotai/Kimi-K3 \
    --generation-workers 16 \
    --judge-workers 1 \
    --parallel 20 \
    --retries 8 \
    --transport-timeout 10800 \
    --stage generate
