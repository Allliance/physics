#!/usr/bin/env bash

#SBATCH --job-name=qwen3-4b-prism-binary-eval
#SBATCH --partition=amd-mi355x
#SBATCH --exclude=mi355-gpu-11
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=128
#SBATCH --mem=1400000M
#SBATCH --time=01:00:00
#SBATCH --output=/shared/data/home/aa3242/physics/rlvr/runs/slurm/%x-%j.out
#SBATCH --error=/shared/data/home/aa3242/physics/rlvr/runs/slurm/%x-%j.err

set -euo pipefail

repo_root=/shared/data/home/aa3242/physics
judge_image=${JUDGE_VLLM_IMAGE:-rocm/vllm:rocm7.13.0_gfx950-dcgpu_ubuntu24.04_py3.13_pytorch_2.10.0_vllm_0.19.1}
judge_model=${JUDGE_MODEL:-Qwen/Qwen3.5-27B}
judge_dp=${JUDGE_DP_SIZE:-4}
judge_tp=${JUDGE_TP_SIZE:-1}
judge_port=${JUDGE_PORT:-8000}
input=${BINARY_EVAL_INPUT:-$repo_root/rlvr/runs/llm-judge-train-20403/training/validation/0.jsonl}
run_root=${BINARY_EVAL_RUN_ROOT:-$repo_root/rlvr/runs/binary-eval-qwen3-4b-initial-$SLURM_JOB_ID}
judge_container="physics-binary-eval-judge-$SLURM_JOB_ID"
mkdir -p "$run_root" "$repo_root/rlvr/runs/slurm"

if [[ "$judge_dp" -ne 4 || "$judge_tp" -ne 1 ]]; then
    echo "Binary evaluation requires judge DP=4 and TP=1" >&2
    exit 2
fi
if [[ ! -f "$input" ]]; then
    echo "Binary evaluation input does not exist: $input" >&2
    exit 2
fi

cleanup() {
    sudo -n docker rm -f "$judge_container" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

gpu_csv=${SLURM_JOB_GPUS:-0,1,2,3}
{
    echo "job_id=$SLURM_JOB_ID"
    echo "node=$(hostname)"
    echo "judge_model=$judge_model"
    echo "judge_gpus=$gpu_csv"
    echo "judge_data_parallel_size=$judge_dp"
    echo "judge_tensor_parallel_size=$judge_tp"
    echo "input=$input"
    echo "started_at=$(date -Is)"
} | tee "$run_root/allocation.txt"

if ! sudo -n docker image inspect "$judge_image" >/dev/null 2>&1; then
    sudo -n docker pull "$judge_image"
fi
cleanup

sudo -n docker run --detach \
    --name "$judge_container" \
    --network host \
    --ipc host \
    --device=/dev/kfd \
    --device=/dev/dri \
    --group-add=video \
    --cap-add=SYS_PTRACE \
    --security-opt seccomp=unconfined \
    --shm-size=256g \
    --volume /shared/data/home/aa3242/.cache/huggingface:/root/.cache/huggingface:ro \
    --env "CUDA_VISIBLE_DEVICES=$gpu_csv" \
    --env HF_HUB_OFFLINE=1 \
    --env TRANSFORMERS_OFFLINE=1 \
    --entrypoint /opt/python/bin/vllm \
    "$judge_image" \
    serve "$judge_model" \
    --host 0.0.0.0 \
    --port "$judge_port" \
    --served-model-name "$judge_model" \
    --dtype bfloat16 \
    --tensor-parallel-size "$judge_tp" \
    --data-parallel-size "$judge_dp" \
    --gpu-memory-utilization 0.94 \
    --max-model-len 32768 \
    --max-num-seqs 256 \
    --max-num-batched-tokens 65536 \
    --enable-prefix-caching \
    --enable-chunked-prefill \
    --generation-config vllm \
    --attention-backend TRITON_ATTN \
    --trust-remote-code \
    >"$run_root/judge-container-id.txt"

sudo -n docker logs --follow "$judge_container" >"$run_root/judge-vllm.log" 2>&1 &
logger_pid=$!
ready=0
for _ in $(seq 1 240); do
    if sudo -n docker logs "$judge_container" >"$run_root/judge-startup.pending.log" 2>&1 && \
        grep -q 'Application startup complete' "$run_root/judge-startup.pending.log" && \
        curl --fail --silent "http://127.0.0.1:$judge_port/v1/models" >"$run_root/models.json"; then
        ready=1
        break
    fi
    if ! sudo -n docker inspect --format '{{.State.Running}}' "$judge_container" 2>/dev/null | grep -qx true; then
        echo "Judge vLLM container exited during startup" >&2
        sudo -n docker logs "$judge_container" >&2 || true
        exit 1
    fi
    sleep 5
done
if [[ "$ready" -ne 1 ]]; then
    echo "Judge vLLM did not become healthy within 20 minutes" >&2
    exit 1
fi

export PYTHONPATH="$repo_root"
export LLM_JUDGE_BASE_URL="http://127.0.0.1:$judge_port/v1"
export LLM_JUDGE_MODEL="$judge_model"
export LLM_JUDGE_MAX_TOKENS=${LLM_JUDGE_MAX_TOKENS:-384}
export LLM_JUDGE_RETRIES=${LLM_JUDGE_RETRIES:-3}
export LLM_JUDGE_PARSE_RETRIES=${LLM_JUDGE_PARSE_RETRIES:-3}

python3 -m rlvr.evaluate_binary \
    "$input" \
    "$run_root/judgments.jsonl" \
    --workers "${BINARY_EVAL_WORKERS:-64}" \
    --timeout "${BINARY_EVAL_TIMEOUT:-180}" \
    | tee "$run_root/summary.stdout.json"

date -Is >"$run_root/completed.txt"
cleanup
wait "$logger_pid" || true
