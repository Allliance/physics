#!/usr/bin/env bash

set -euo pipefail

repo_root=/shared/data/home/aa3242/physics
image=rocm/vllm:rocm7.13.0_gfx950-dcgpu_ubuntu24.04_py3.13_pytorch_2.10.0_vllm_0.19.1
container=qwen35-9b-vllm-${SLURM_JOB_ID}
model=Qwen/Qwen3.5-9B
port=8000
run_root="$repo_root/model_evals/qwen/runs/qwen35-9b-server-${SLURM_JOB_ID}"

mkdir -p "$run_root"
cleanup() {
    sudo -n docker rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

{
    echo "job_id=$SLURM_JOB_ID"
    echo "node=$(hostname)"
    echo "started_at=$(date -Is)"
    echo "image=$image"
    echo "model=$model"
    echo "data_parallel_size=8"
    echo "max_num_seqs=256"
    echo "max_model_len=32768"
} | tee "$run_root/allocation.txt"

rocm-smi --showproductname >"$run_root/gpus.txt" 2>&1
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
    --volume /shared/data/home/aa3242/.cache/huggingface:/root/.cache/huggingface:ro \
    --env HF_HUB_OFFLINE=1 \
    --env TRANSFORMERS_OFFLINE=1 \
    --entrypoint /opt/python/bin/vllm \
    "$image" \
    serve \
    "$model" \
    --host 0.0.0.0 \
    --port "$port" \
    --served-model-name "$model" \
    --dtype bfloat16 \
    --enforce-eager \
    --max-model-len 32768 \
    --data-parallel-size 8 \
    --max-num-seqs 256 \
    --gpu-memory-utilization 0.95 \
    --reasoning-parser qwen3 \
    --reasoning-config '{"reasoning_start_str":"<think>","reasoning_end_str":"</think>"}' \
    --trust-remote-code \
    >"$run_root/container-id.txt"

sudo -n docker logs --follow "$container" >"$run_root/vllm.log" 2>&1 &
logger_pid=$!
ready=0
for _ in $(seq 1 180); do
    if curl --fail --silent "http://127.0.0.1:${port}/v1/models" >"$run_root/models.json"; then
        ready=1
        break
    fi
    if ! sudo -n docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null | grep -qx true; then
        echo "vLLM container exited during startup" >&2
        sudo -n docker logs "$container" >&2 || true
        exit 1
    fi
    sleep 5
done
if [[ "$ready" != 1 ]]; then
    echo "vLLM did not become healthy within 15 minutes" >&2
    exit 1
fi

cat >"$run_root/endpoint.json" <<EOF
{
  "job_id": "$SLURM_JOB_ID",
  "node": "$(hostname)",
  "base_url": "http://$(hostname):${port}/v1",
  "model": "$model",
  "data_parallel_size": 8,
  "max_num_seqs": 256,
  "max_model_len": 32768
}
EOF
date -Is >"$run_root/ready.txt"
echo "server ready at http://$(hostname):${port}/v1"

while true; do
    if ! sudo -n docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null | grep -qx true; then
        echo "vLLM container stopped unexpectedly" >&2
        wait "$logger_pid" || true
        exit 1
    fi
    sleep 60
done
