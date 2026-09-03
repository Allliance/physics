#!/usr/bin/env bash
#SBATCH --job-name=llm-judge-qwen35-27b
#SBATCH --partition=amd-mi355x
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=256G
#SBATCH --gres=gpu:4
#SBATCH --time=04:00:00
#SBATCH --output=/shared/data/home/aa3242/physics/llm_judge/judge-server-%j.log
#SBATCH --error=/shared/data/home/aa3242/physics/llm_judge/judge-server-%j.log

set -euo pipefail

script_path=$(readlink -f "${BASH_SOURCE[0]}")

if [[ -z "${SLURM_JOB_ID:-}" ]]; then
    preferred_node=${JUDGE_SERVER_NODE:-mi355-gpu-36}
    exec sbatch --nodelist="$preferred_node" "$script_path"
fi

repo_root=${JUDGE_SERVER_REPO_ROOT:-/shared/data/home/aa3242/physics}
model=${JUDGE_SERVER_MODEL:-Qwen/Qwen3.5-27B}
image=${JUDGE_SERVER_IMAGE:-rocm/vllm:rocm7.13.0_gfx950-dcgpu_ubuntu24.04_py3.13_pytorch_2.10.0_vllm_0.19.1}
vllm_entrypoint=${JUDGE_SERVER_VLLM_ENTRYPOINT:-/opt/python/bin/vllm}
max_model_len=${JUDGE_SERVER_MAX_MODEL_LEN:-32768}
max_num_seqs=${JUDGE_SERVER_MAX_NUM_SEQS:-256}
port=${JUDGE_SERVER_PORT:-$((10000 + SLURM_JOB_ID % 10000))}
visible_devices=${ROCR_VISIBLE_DEVICES:-${CUDA_VISIBLE_DEVICES:-0,1,2,3}}
container="llm-judge-qwen35-27b-${SLURM_JOB_ID}"
runs_root="$repo_root/llm_judge/server_runs"
run_root="$runs_root/$SLURM_JOB_ID"

mkdir -p "$run_root"

if sudo -n docker info >/dev/null 2>&1; then
    docker_command=(sudo -n docker)
elif docker info >/dev/null 2>&1; then
    docker_command=(docker)
else
    echo "Docker is unavailable for the current user on $(hostname)" >&2
    exit 1
fi

cleanup() {
    "${docker_command[@]}" rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

{
    echo "job_id=$SLURM_JOB_ID"
    echo "node=$(hostname)"
    echo "started_at=$(date -Is)"
    echo "image=$image"
    echo "model=$model"
    echo "port=$port"
    echo "data_parallel_size=4"
    echo "max_num_seqs=$max_num_seqs"
    echo "max_model_len=$max_model_len"
} >"$run_root/allocation.txt"

rocm-smi --showproductname >"$run_root/gpus.txt" 2>&1
if ! "${docker_command[@]}" image inspect "$image" >/dev/null 2>&1; then
    "${docker_command[@]}" pull "$image"
fi
"${docker_command[@]}" rm -f "$container" >/dev/null 2>&1 || true

"${docker_command[@]}" run --detach \
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
    --env ROCR_VISIBLE_DEVICES="$visible_devices" \
    --env HIP_VISIBLE_DEVICES="$visible_devices" \
    --env CUDA_VISIBLE_DEVICES="$visible_devices" \
    --entrypoint "$vllm_entrypoint" \
    "$image" \
    serve \
    "$model" \
    --host 0.0.0.0 \
    --port "$port" \
    --served-model-name "$model" \
    --dtype bfloat16 \
    --enforce-eager \
    --max-model-len "$max_model_len" \
    --data-parallel-size 4 \
    --max-num-seqs "$max_num_seqs" \
    --gpu-memory-utilization 0.95 \
    --attention-backend TRITON_ATTN \
    --enable-prefix-caching \
    --reasoning-parser qwen3 \
    --reasoning-config '{"reasoning_start_str":"<think>","reasoning_end_str":"</think>"}' \
    --trust-remote-code \
    >"$run_root/container-id.txt"

"${docker_command[@]}" logs --follow "$container" >"$run_root/vllm.log" 2>&1 &
logger_pid=$!
ready=0
for _ in $(seq 1 180); do
    if curl --fail --silent "http://127.0.0.1:${port}/v1/models" \
        >"$run_root/models.pending.json"; then
        if python3 -c 'import json, sys; data=json.load(open(sys.argv[1])); sys.exit(not any(item.get("id") == sys.argv[2] for item in data.get("data", [])))' \
            "$run_root/models.pending.json" "$model"; then
            mv "$run_root/models.pending.json" "$run_root/models.json"
            ready=1
            break
        fi
    fi
    if ! "${docker_command[@]}" inspect --format '{{.State.Running}}' "$container" \
        2>/dev/null | grep -qx true; then
        echo "vLLM container exited during startup" >&2
        "${docker_command[@]}" logs "$container" >&2 || true
        exit 1
    fi
    sleep 5
done
if [[ "$ready" != 1 ]]; then
    echo "vLLM did not become healthy within 15 minutes" >&2
    exit 1
fi

node=$(hostname)
base_url="http://${node}:${port}/v1"
cat >"$run_root/endpoint.json" <<EOF
{
  "job_id": "$SLURM_JOB_ID",
  "node": "$node",
  "base_url": "$base_url",
  "model": "$model",
  "data_parallel_size": 4,
  "max_num_seqs": $max_num_seqs,
  "max_model_len": $max_model_len
}
EOF
cat >"$run_root/endpoint.env" <<EOF
export OPENAI_BASE_URL='$base_url'
export OPENAI_MODEL='$model'
export OPENAI_API_KEY='EMPTY'
EOF
date -Is >"$run_root/ready.txt"
echo "server ready at $base_url"
echo "endpoint environment: $run_root/endpoint.env"

while true; do
    if ! "${docker_command[@]}" inspect --format '{{.State.Running}}' "$container" \
        2>/dev/null | grep -qx true; then
        echo "vLLM container stopped unexpectedly" >&2
        wait "$logger_pid" || true
        exit 1
    fi
    sleep 60
done
