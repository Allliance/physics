#!/usr/bin/env bash
set -euo pipefail

model_key=${1:?usage: run_original_after_corrected.sh kimi|glm|deepseek}
repo=/shared/data/home/aa3242/physics

case "$model_key" in
    kimi)
        directory=kimi
        tag=kimi-k3-max-no-tools-20260917
        endpoint_model=moonshotai/Kimi-K3
        ;;
    glm)
        directory=glm
        tag=glm-5.3-max-no-tools-20260917
        endpoint_model=zai-org/GLM-5.3
        ;;
    deepseek)
        directory=deepseek
        tag=deepseek-v4-pro-max-no-tools-20260917
        endpoint_model=deepseek-ai/DeepSeek-V4-Pro
        generation_workers=42
        ;;
    *)
        echo "Unknown model key: $model_key" >&2
        exit 2
        ;;
esac

generation_workers=${generation_workers:-14}

run="$repo/model_evals/$directory/runs/$tag"
corrected="$run/hle-corrected/summary.json"
mkdir -p "$run/native-original"

while ! "$repo/model_evals/gemini/.venv/bin/python" - "$corrected" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
raise SystemExit(0 if path.exists() and json.loads(path.read_text()).get("complete") else 1)
PY
do
    curl --fail --silent http://127.0.0.1:8000/v1/models | grep -q "$endpoint_model"
    sleep 30
done

date -Is >"$run/native-original/started.txt"
"$repo/model_evals/gemini/.venv/bin/python" -u \
    "$repo/model_evals/open_models/run_original_native.py" \
    --model "$model_key" --base-url http://127.0.0.1:8000/v1 \
    --generation-workers "$generation_workers" --retries 4 --stage all \
    >>"$run/native-original/supervisor.log" 2>&1
date -Is >"$run/native-original/complete.txt"
