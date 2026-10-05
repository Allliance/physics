#!/usr/bin/env bash
set -euo pipefail

repo=/shared/data/home/aa3242/physics
cache=/shared/data/home/aa3242/.cache/huggingface
image=${KIMI_VLLM_IMAGE:-vllm/vllm-openai-rocm:kimi-k3}
model=moonshotai/Kimi-K3
port=${KIMI_PORT:-8000}
container=kimi-k3-vllm-reservation-${SLURM_JOB_ID}
run="$repo/model_evals/kimi/runs/server-reservation-${SLURM_JOB_ID}"
mkdir -p "$run" "$cache"

cleanup() {
    sudo -n docker rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

{
    echo "job_id=$SLURM_JOB_ID"
    echo "step_id=${SLURM_STEP_ID:-unknown}"
    echo "node=$(hostname)"
    echo "started_at=$(date -Is)"
    echo "image=$image"
    echo "model=$model"
    echo "tensor_parallel_size=8"
    echo "reasoning_effort=max"
    echo "max_model_len=81920"
} >"$run/allocation.txt"
rocm-smi --showproductname >"$run/gpus.txt" 2>&1

if ! sudo -n docker image inspect "$image" >/dev/null 2>&1; then
    sudo -n docker pull "$image"
fi
sudo -n docker rm -f "$container" >/dev/null 2>&1 || true
sudo -n docker run --detach \
    --name "$container" \
    --network host \
    --ipc host \
    --device=/dev/kfd \
    --device=/dev/dri \
    --group-add=video \
    --cap-add=SYS_PTRACE \
    --security-opt seccomp=unconfined \
    --volume "$cache:/root/.cache/huggingface" \
    --env VLLM_ROCM_USE_AITER=1 \
    --env SAFETENSORS_FAST_GPU=1 \
    --env VLLM_ROCM_USE_AITER_MOE_SITUV2=1 \
    --env VLLM_ROCM_USE_AITER_MOE_SITUV2_A8W4=1 \
    --env VLLM_USE_BREAKABLE_CUDAGRAPH=0 \
    --entrypoint /usr/local/bin/vllm \
    "$image" serve "$model" \
    --host 0.0.0.0 \
    --port "$port" \
    --served-model-name "$model" \
    --tensor-parallel-size 8 \
    --max-model-len 81920 \
    --max-num-seqs 128 \
    --max-num-batched-tokens 4096 \
    --gpu-memory-utilization 0.95 \
    --load-format auto \
    --mm-encoder-tp-mode data \
    --reasoning-parser kimi_k3 \
    --compilation-config '{"cudagraph_mode":"FULL_DECODE_ONLY","custom_ops":["+fused_rms_norm_gated"]}' \
    --trust-remote-code >"$run/container-id.txt"

sudo -n docker logs --follow "$container" >"$run/vllm.log" 2>&1 &
logger_pid=$!
ready=0
for _ in $(seq 1 4320); do
    if curl --fail --silent "http://127.0.0.1:${port}/v1/models" >"$run/models.pending.json"; then
        mv "$run/models.pending.json" "$run/models.json"
        ready=1
        break
    fi
    if ! sudo -n docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null | grep -qx true; then
        sudo -n docker logs "$container" >&2 || true
        exit 1
    fi
    sleep 10
done
[[ "$ready" == 1 ]] || { echo "Kimi vLLM startup did not complete within 12 hours" >&2; exit 1; }

cat >"$run/endpoint.json" <<EOF
{
  "job_id": "$SLURM_JOB_ID",
  "step_id": "${SLURM_STEP_ID:-unknown}",
  "node": "$(hostname)",
  "base_url": "http://$(hostname):${port}/v1",
  "model": "$model",
  "reasoning_parser": "kimi_k3",
  "reasoning_effort": "max",
  "tensor_parallel_size": 8,
  "max_model_len": 81920
}
EOF
date -Is >"$run/ready.txt"
ln -sfn "server-reservation-${SLURM_JOB_ID}" "$repo/model_evals/kimi/runs/current-server"

wait "$logger_pid"
