#!/usr/bin/env bash
set -uo pipefail

allocation=${1:?usage: watch_sequence.sh ALLOCATION_ID KIMI_SERVER_STEP}
kimi_server_step=${2:?usage: watch_sequence.sh ALLOCATION_ID KIMI_SERVER_STEP}
repo=/shared/data/home/aa3242/physics
python="$repo/model_evals/gemini/.venv/bin/python"
log="$repo/model_evals/open_models/sequence-watch-${allocation}.log"

kimi_run="$repo/model_evals/kimi/runs/kimi-k3-max-no-tools-20260917"
deepseek_run="$repo/model_evals/deepseek/runs/deepseek-v4-pro-max-no-tools-20260917"

json_complete() {
    "$python" - "$1" <<'PY' >/dev/null 2>&1
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
raise SystemExit(0 if path.exists() and json.loads(path.read_text()).get("complete") else 1)
PY
}

process_live() {
    local pattern=$1
    pgrep -af "$pattern" | grep -v '[w]atch_sequence.sh' >/dev/null 2>&1
}

mkdir -p "$(dirname "$log")"
exec >>"$log" 2>&1
echo "$(date -Is) watchdog started allocation=$allocation kimi_server_step=$kimi_server_step"

while true; do
    if json_complete "$deepseek_run/native-original/suite-summary.json"; then
        echo "$(date -Is) complete: DeepSeek native suite marker present; watchdog exiting"
        exit 0
    fi

    metrics=$(curl --fail --silent http://127.0.0.1:8000/metrics 2>/dev/null || true)
    model=$(curl --fail --silent http://127.0.0.1:8000/v1/models 2>/dev/null \
        | "$python" -c 'import json,sys; x=json.load(sys.stdin); print(x["data"][0]["id"])' 2>/dev/null || true)
    running=$(awk '/^vllm:num_requests_running/{print $2; exit}' <<<"$metrics")
    waiting=$(awk '/^vllm:num_requests_waiting\{/{print $2; exit}' <<<"$metrics")
    echo "$(date -Is) model=${model:-down} running=${running:-na} waiting=${waiting:-na}"

    if json_complete "$kimi_run/hle-corrected/summary.json" \
        && ! json_complete "$kimi_run/native-original/suite-summary.json" \
        && ! process_live '[r]un_original_after_corrected.sh kimi' \
        && ! process_live '[r]un_original_native.py --model kimi'; then
        echo "$(date -Is) recovery: Kimi original supervisor is absent; resuming it"
        bash "$repo/model_evals/open_models/jobs/run_original_after_corrected.sh" kimi
        code=$?
        echo "$(date -Is) recovery: Kimi original supervisor exited code=$code"
    fi

    if json_complete "$kimi_run/native-original/suite-summary.json" \
        && ! process_live '[e]valuate_remaining_models_in_allocation.sh'; then
        echo "$(date -Is) recovery: GLM/DeepSeek sequence supervisor is absent; resuming it"
        bash "$repo/model_evals/open_models/jobs/evaluate_remaining_models_in_allocation.sh" "$kimi_server_step"
        code=$?
        echo "$(date -Is) recovery: GLM/DeepSeek sequence supervisor exited code=$code"
    fi

    sleep 60
done
