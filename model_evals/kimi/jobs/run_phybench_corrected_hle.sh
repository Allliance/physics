#!/usr/bin/env bash
set -uo pipefail

repo=/shared/data/home/aa3242/physics
python="$repo/model_evals/gemini/.venv/bin/python"
dataset="$repo/model_evals/gemini/runs/gemini31-20260908/phybench/corrected/dataset.json"
run="$repo/model_evals/kimi/runs/kimi-k3-max-no-tools-20260917/hle-corrected/phybench"
generation_workers_per_attempt=32
judge_workers_per_attempt=8
max_invocations=5

export OPENAI_COMPAT_MODEL=moonshotai/Kimi-K3

mkdir -p "$run/logs"

run_attempt() {
    local attempt=$1
    local output="$run/attempt-$attempt"
    local log="$run/logs/attempt-$attempt.log"
    local code=2
    local count=0

    # Attempt 1 began as the end-to-end smoke from the login host. Preserve its
    # endpoint fingerprint when resuming; both URLs target the same vLLM server.
    if [[ "$attempt" == 1 ]]; then
        export OPENAI_COMPAT_BASE_URL=http://mi355-gpu-35:8000/v1
    else
        export OPENAI_COMPAT_BASE_URL=http://127.0.0.1:8000/v1
    fi

    for invocation in $(seq 1 "$max_invocations"); do
        printf '\n[%s] generation invocation %s\n' "$(date -Is)" "$invocation" >>"$log"
        "$python" -u -m eval \
            --dataset phybench-frozen-gemini-corrected \
            --data "$dataset" \
            --split corrected \
            --output "$output" \
            --model kimi-k3 \
            --judge-model gpt-5.6-sol \
            --reasoning-effort max \
            --judge-reasoning-effort high \
            --mode merged \
            --max-output-tokens 65536 \
            --judge-max-output-tokens 32768 \
            --timeout 3600 \
            --workers "$generation_workers_per_attempt" \
            --stage generate >>"$log" 2>&1
        code=$?
        count=$("$python" -c 'import json, pathlib, sys; p=pathlib.Path(sys.argv[1]); print(len(json.loads(p.read_text())) if p.exists() else 0)' "$output/predictions.json")
        printf '[%s] generation exit %s; predictions %s/88\n' "$(date -Is)" "$code" "$count" >>"$log"
        [[ "$count" == 88 ]] && break
        [[ "$code" == 1 ]] && break
        sleep 30
    done
    if [[ "$count" != 88 ]]; then
        printf '%s\n' 2 >"$run/attempt-$attempt.exit-code"
        return 2
    fi

    for invocation in $(seq 1 "$max_invocations"); do
        printf '\n[%s] judgment invocation %s\n' "$(date -Is)" "$invocation" >>"$log"
        "$python" -u -m eval \
            --dataset phybench-frozen-gemini-corrected \
            --data "$dataset" \
            --split corrected \
            --output "$output" \
            --model kimi-k3 \
            --judge-model gpt-5.6-sol \
            --reasoning-effort max \
            --judge-reasoning-effort high \
            --mode merged \
            --max-output-tokens 65536 \
            --judge-max-output-tokens 32768 \
            --timeout 3600 \
            --workers "$judge_workers_per_attempt" \
            --stage judge >>"$log" 2>&1
        code=$?
        printf '[%s] judgment exit %s\n' "$(date -Is)" "$code" >>"$log"
        [[ "$code" == 0 ]] && break
        [[ "$code" == 1 ]] && break
        sleep 30
    done
    printf '%s\n' "$code" >"$run/attempt-$attempt.exit-code"
    return "$code"
}

pids=()
for attempt in 1 2 3 4; do
    run_attempt "$attempt" &
    pids+=("$!")
done

failed=0
for pid in "${pids[@]}"; do
    wait "$pid" || failed=1
done

"$python" "$repo/model_evals/kimi/summarize_phybench_corrected_hle.py" "$run" || true

exit "$failed"
