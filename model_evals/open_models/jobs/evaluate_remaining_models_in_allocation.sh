#!/usr/bin/env bash
set -euo pipefail

kimi_server_step=${1:?usage: evaluate_remaining_models_in_allocation.sh KIMI_SERVER_STEP}
repo=/shared/data/home/aa3242/physics
cache=/shared/data/home/aa3242/.cache/huggingface
python="$repo/model_evals/gemini/.venv/bin/python"
port=8000
current_container=
logger_pid=
cd "$repo"

cleanup() {
    if [[ -n "${current_container:-}" ]]; then
        sudo -n docker rm -f "$current_container" >/dev/null 2>&1 || true
    fi
    if [[ -n "${logger_pid:-}" ]]; then
        kill "$logger_pid" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT INT TERM

json_complete() {
    "$python" - "$1" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
raise SystemExit(0 if path.exists() and json.loads(path.read_text()).get("complete") else 1)
PY
}

kimi_summary="$repo/model_evals/kimi/runs/kimi-k3-max-no-tools-20260917/native-original/suite-summary.json"
while ! json_complete "$kimi_summary"; do
    curl --fail --silent "http://127.0.0.1:${port}/v1/models" | grep -q 'moonshotai/Kimi-K3'
    sleep 30
done

scancel "$kimi_server_step"
for _ in $(seq 1 120); do
    if ! curl --fail --silent "http://127.0.0.1:${port}/v1/models" >/dev/null 2>&1; then
        break
    fi
    sleep 2
done
if curl --fail --silent "http://127.0.0.1:${port}/v1/models" >/dev/null 2>&1; then
    echo "Kimi server did not stop cleanly" >&2
    exit 1
fi

serve_and_evaluate() {
    local key=$1
    local directory model tag image generation_workers original_key corrected_key
    local -a model_args docker_env

    case "$key" in
        glm)
            directory=glm
            model=zai-org/GLM-5.3
            tag=glm-5.3-max-no-tools-20260917
            image=vllm/vllm-openai-rocm:nightly
            generation_workers=8
            original_key=glm
            corrected_key=glm-5.3
            model_args=(
                --kv-cache-dtype fp8_e4m3
                --max-num-seqs 128
                --gpu-memory-utilization 0.80
                --speculative-config '{"method":"mtp","num_speculative_tokens":5}'
                --reasoning-parser glm45
                --tool-call-parser glm47
                --enable-auto-tool-choice
                --linear-backend aiter
                --moe-backend aiter
            )
            docker_env=(
                --env VLLM_ROCM_USE_AITER=1
                --env VLLM_ROCM_USE_AITER_FUSION_SHARED_EXPERTS=1
                --env VLLM_ENGINE_READY_TIMEOUT_S=43200
            )
            ;;
        deepseek)
            directory=deepseek
            model=deepseek-ai/DeepSeek-V4-Pro
            tag=deepseek-v4-pro-max-no-tools-20260917
            image=vllm/vllm-openai-rocm:nightly-eed1f3d0c6043bd494424a22443ee198dd56f657
            generation_workers=22
            original_key=deepseek
            corrected_key=deepseek-v4-pro
            model_args=(
                --dtype auto
                --kv-cache-dtype fp8
                --max-num-seqs 512
                --distributed-executor-backend mp
                --gpu-memory-utilization 0.90
                --tokenizer-mode deepseek_v4
                --reasoning-parser deepseek_v4
                --tool-call-parser deepseek_v4
                --enable-auto-tool-choice
                --moe-backend aiter
                --async-scheduling
                --compilation-config '{"mode":3,"cudagraph_mode":"FULL_AND_PIECEWISE"}'
            )
            docker_env=(
                --env VLLM_ROCM_USE_AITER=1
                --env VLLM_ROCM_QUICK_REDUCE_QUANTIZATION=INT4
                --env VLLM_ROCM_USE_AITER_MOE=1
                --env VLLM_ROCM_USE_AITER_FUSION_SHARED_EXPERTS=0
                --env VLLM_ENGINE_READY_TIMEOUT_S=43200
                --env VLLM_PREFIX_CACHE_RETENTION_INTERVAL=32768
            )
            ;;
        *)
            echo "Unknown model: $key" >&2
            return 2
            ;;
    esac

    local run="$repo/model_evals/$directory/runs/$tag"
    local server="$repo/model_evals/$directory/runs/server-reservation-${SLURM_JOB_ID}-${key}"
    mkdir -p "$run/hle-corrected" "$run/native-original" "$server" "$cache"
    date -Is >"$server/preparing.txt"

    HF_HOME="$cache" HF_XET_HIGH_PERFORMANCE=1 "$python" - "$model" "$cache/hub" <<'PY'
import sys
from huggingface_hub import snapshot_download

print(snapshot_download(sys.argv[1], cache_dir=sys.argv[2], max_workers=16))
PY
    sudo -n docker image inspect "$image" >/dev/null 2>&1 || sudo -n docker pull "$image"

    current_container="${key}-vllm-sequence-${SLURM_JOB_ID}"
    sudo -n docker rm -f "$current_container" >/dev/null 2>&1 || true
    sudo -n docker run --detach \
        --name "$current_container" \
        --network host \
        --ipc host \
        --device=/dev/kfd \
        --device=/dev/dri \
        --group-add=video \
        --cap-add=SYS_PTRACE \
        --security-opt seccomp=unconfined \
        --volume "$cache:/root/.cache/huggingface" \
        "${docker_env[@]}" \
        --entrypoint /usr/local/bin/vllm \
        "$image" serve "$model" \
        --host 0.0.0.0 \
        --port "$port" \
        --served-model-name "$model" \
        --tensor-parallel-size 8 \
        --max-model-len 131072 \
        --max-num-batched-tokens 8192 \
        --trust-remote-code \
        "${model_args[@]}" >"$server/container-id.txt"

    sudo -n docker logs --follow "$current_container" >"$server/vllm.log" 2>&1 &
    logger_pid=$!
    local ready=0
    for _ in $(seq 1 4320); do
        if curl --fail --silent "http://127.0.0.1:${port}/v1/models" >"$server/models.pending.json"; then
            if grep -q "$model" "$server/models.pending.json"; then
                mv "$server/models.pending.json" "$server/models.json"
                ready=1
                break
            fi
        fi
        if ! sudo -n docker inspect --format '{{.State.Running}}' "$current_container" 2>/dev/null | grep -qx true; then
            sudo -n docker logs "$current_container" >&2 || true
            return 1
        fi
        sleep 10
    done
    [[ "$ready" == 1 ]] || { echo "$model did not become ready" >&2; return 1; }

    cat >"$server/endpoint.json" <<EOF
{
  "job_id": "$SLURM_JOB_ID",
  "step_id": "${SLURM_STEP_ID:-unknown}",
  "node": "$(hostname)",
  "base_url": "http://$(hostname):${port}/v1",
  "model": "$model",
  "reasoning_effort": "max",
  "max_model_len": 131072
}
EOF
    date -Is >"$server/ready.txt"
    ln -sfn "server-reservation-${SLURM_JOB_ID}-${key}" "$repo/model_evals/$directory/runs/current-server"

    OPENAI_COMPAT_BASE_URL="http://127.0.0.1:${port}/v1" OPENAI_COMPAT_MODEL="$model" \
        "$python" - "$key" >"$run/smoke.json" <<'PY'
import json
import os
import sys
from utils.openai_compatible import generate

key = sys.argv[1]
result = generate(
    "Return the integer obtained by adding 2 and 2.",
    system_prompt="Solve the problem and return only the requested JSON object.",
    reasoning_effort="max",
    max_output_tokens=8192,
    timeout=1800,
    temperature=1.0,
    top_p=1.0 if key == "deepseek" else 0.95,
    output_schema={
        "type": "object",
        "properties": {"answer": {"type": "integer"}},
        "required": ["answer"],
        "additionalProperties": False,
    },
)
if json.loads(result["response"])["answer"] != 4:
    raise ValueError(f"Smoke answer failed: {result}")
print(json.dumps(result, indent=2))
PY
    date -Is >"$run/smoke-complete.txt"

    OPENAI_COMPAT_BASE_URL="http://127.0.0.1:${port}/v1" OPENAI_COMPAT_MODEL="$model" \
        "$python" -u "$repo/model_evals/open_models/run_corrected_hle.py" \
        --model "$corrected_key" \
        --generation-workers "$generation_workers" --judge-workers 10 \
        --parallel 24 --retries 4 --base-url "http://127.0.0.1:${port}/v1" --stage all \
        >>"$run/hle-corrected/supervisor.log" 2>&1
    json_complete "$run/hle-corrected/summary.json"

    local original_workers=14
    [[ "$key" == deepseek ]] && original_workers=42
    OPENAI_COMPAT_BASE_URL="http://127.0.0.1:${port}/v1" OPENAI_COMPAT_MODEL="$model" \
        "$python" -u "$repo/model_evals/open_models/run_original_native.py" \
        --model "$original_key" --base-url "http://127.0.0.1:${port}/v1" \
        --generation-workers "$original_workers" --retries 4 --stage all \
        >>"$run/native-original/supervisor.log" 2>&1
    json_complete "$run/native-original/suite-summary.json"
    date -Is >"$run/complete.txt"

    sudo -n docker rm -f "$current_container" >/dev/null 2>&1 || true
    current_container=
    kill "$logger_pid" >/dev/null 2>&1 || true
    wait "$logger_pid" >/dev/null 2>&1 || true
    logger_pid=
}

serve_and_evaluate glm
serve_and_evaluate deepseek
