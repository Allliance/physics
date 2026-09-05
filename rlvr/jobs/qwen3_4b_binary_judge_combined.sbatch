#!/usr/bin/env bash

#SBATCH --job-name=qwen3-4b-binary-rlvr
#SBATCH --partition=amd-mi355x
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:8
#SBATCH --cpus-per-task=256
#SBATCH --mem=2800G
#SBATCH --time=12:00:00
#SBATCH --output=/shared/data/home/aa3242/physics/rlvr/runs/slurm/%x-%j.out
#SBATCH --error=/shared/data/home/aa3242/physics/rlvr/runs/slurm/%x-%j.err

set -euo pipefail

repo_root=/shared/data/home/aa3242/physics
judge_port=$((10000 + SLURM_JOB_ID % 10000))
judge_run="$repo_root/llm_judge/server_runs/$SLURM_JOB_ID"
judge_pid=

cleanup() {
    if [[ -n "$judge_pid" ]]; then
        kill "$judge_pid" >/dev/null 2>&1 || true
        wait "$judge_pid" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT INT TERM

# One external vLLM replica per judge GPU: DP=4, TP=1.
ROCR_VISIBLE_DEVICES=0,1,2,3 \
HIP_VISIBLE_DEVICES=0,1,2,3 \
CUDA_VISIBLE_DEVICES=0,1,2,3 \
JUDGE_SERVER_PORT="$judge_port" \
    /bin/bash "$repo_root/llm_judge/start_judge_server.sh" &
judge_pid=$!

for _ in $(seq 1 180); do
    if [[ -s "$judge_run/endpoint.json" && -f "$judge_run/ready.txt" ]]; then
        break
    fi
    if ! kill -0 "$judge_pid" 2>/dev/null; then
        echo "Judge server exited before becoming healthy" >&2
        wait "$judge_pid"
    fi
    sleep 5
done
if [[ ! -s "$judge_run/endpoint.json" || ! -f "$judge_run/ready.txt" ]]; then
    echo "Judge server did not become healthy within 15 minutes" >&2
    exit 1
fi

judge_base_url=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["base_url"])' \
    "$judge_run/endpoint.json")
curl --fail --silent --max-time 10 "$judge_base_url/models" >/dev/null

export RLVR_MODE=train
export RLVR_NGPUS=4
export SLURM_JOB_GPUS=4,5,6,7
export CUDA_VISIBLE_DEVICES=4,5,6,7
export MODEL_PATH=Qwen/Qwen3-4B
export TRAIN_DATASET=prism
export VALIDATION_DATASET=ugphysics
export REWARD_TYPE=binary_llm_judge
export EXPERIMENT_NAME=qwen3-4b-prism-binary-judge
export RLVR_RUN_ROOT=/workspace/physics/rlvr/runs/qwen3-4b-prism-binary-judge
export TRAIN_BATCH_SIZE=16
export PPO_MINI_BATCH_SIZE=16
export ROLLOUT_N=4
export MAX_PROMPT_LENGTH=2048
export MAX_RESPONSE_LENGTH=4096
export TOTAL_EPOCHS=5
export SAVE_FREQ=10
export TEST_FREQ=10
export ACTOR_LR=1e-6
export KL_LOSS_COEF=0.001
export REWARD_NUM_WORKERS=8
export REWARD_TIMEOUT_SECONDS=600
export ROLLOUT_GPU_MEM_UTIL=0.55
export ROLLOUT_TEMPERATURE=0.7
export ROLLOUT_TOP_P=0.95
export ROLLOUT_TOP_K=20
export RESUME_MODE=auto
export TRAINER_LOGGER='["console","wandb"]'
export LLM_JUDGE_BASE_URL="$judge_base_url"
export LLM_JUDGE_MODEL=Qwen/Qwen3.5-27B
export LLM_JUDGE_RETRIES=3
export LLM_JUDGE_PARSE_RETRIES=2
export LLM_JUDGE_BINARY_MAX_TOKENS=6144
export LLM_JUDGE_BINARY_TEMPERATURE=0.6
export LLM_JUDGE_BINARY_TOP_P=0.95
export LLM_JUDGE_BINARY_TOP_K=20
export LLM_JUDGE_BINARY_MIN_P=0
export LLM_JUDGE_BINARY_THINKING_TOKEN_BUDGET=4096
export LLM_JUDGE_RAISE_ERRORS=1
export RAY_OBJECT_STORE_MEMORY_BYTES=20000000000

/bin/bash "$repo_root/rlvr/jobs/qwen3_4b.sbatch"
