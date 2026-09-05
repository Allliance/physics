#!/usr/bin/env bash

#SBATCH --job-name=qwen3-4b-prism-llm-judge
#SBATCH --partition=amd-mi355x
#SBATCH --exclude=mi355-gpu-11
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:8
#SBATCH --cpus-per-task=192
#SBATCH --mem=2800000M
#SBATCH --time=24:00:00
#SBATCH --output=/shared/data/home/aa3242/physics/rlvr/runs/slurm/%x-%j.out
#SBATCH --error=/shared/data/home/aa3242/physics/rlvr/runs/slurm/%x-%j.err

set -euo pipefail

repo_root=/shared/data/home/aa3242/physics
judge_image=${JUDGE_VLLM_IMAGE:-rocm/vllm:rocm7.13.0_gfx950-dcgpu_ubuntu24.04_py3.13_pytorch_2.10.0_vllm_0.19.1}
trainer_image=${VERL_ROCM_IMAGE:-amdagi/verl-dev:rocm7.14_torch2.12_release_0724}
judge_model=${JUDGE_MODEL:-Qwen/Qwen3.5-27B}
mode=${RLVR_MODE:-smoke}
judge_dp=${JUDGE_DP_SIZE:-4}
judge_tp=${JUDGE_TP_SIZE:-1}
judge_port=${JUDGE_PORT:-8000}
train_ngpus=${RLVR_NGPUS:-4}
judge_gpu_count=$((judge_dp * judge_tp))
run_name=${RLVR_RUN_NAME:-llm-judge-$mode-$SLURM_JOB_ID}
run_root="$repo_root/rlvr/runs/$run_name"
judge_container="physics-judge-$SLURM_JOB_ID"
trainer_container="physics-judge-trainer-$SLURM_JOB_ID"
mkdir -p "$run_root" "$repo_root/rlvr/runs/slurm"

if [[ "$judge_gpu_count" -ne 4 ]]; then
    echo "This launch requires exactly four judge GPUs; got DP=$judge_dp TP=$judge_tp" >&2
    exit 2
fi
if [[ "$judge_dp" -ne 4 || "$judge_tp" -ne 1 ]]; then
    echo "Requested topology is DP=4 and TP=1; got DP=$judge_dp TP=$judge_tp" >&2
    exit 2
fi

gpu_csv=${SLURM_JOB_GPUS:-0,1,2,3,4,5,6,7}
IFS=',' read -r -a allocated_gpus <<<"$gpu_csv"
if [[ "$mode" == "serve" ]]; then
    required_gpus=$judge_gpu_count
else
    required_gpus=$((judge_gpu_count + train_ngpus))
fi
if [[ "${#allocated_gpus[@]}" -lt "$required_gpus" ]]; then
    echo "Need $required_gpus allocated GPUs, but SLURM_JOB_GPUS=$gpu_csv" >&2
    exit 2
fi
judge_gpus=$(IFS=,; echo "${allocated_gpus[*]:0:judge_gpu_count}")
trainer_gpus=$(IFS=,; echo "${allocated_gpus[*]:judge_gpu_count:train_ngpus}")

set +u
source /shared/data/home/aa3242/.bashrc
set -u
export WANDB_API_KEY=${WANDB_API_KEY:-${WANDB_TOKEN:-}}
if [[ -z "$WANDB_API_KEY" ]]; then
    echo "WANDB_API_KEY/WANDB_TOKEN is unavailable" >&2
    exit 2
fi

cleanup() {
    sudo -n docker rm -f "$trainer_container" >/dev/null 2>&1 || true
    sudo -n docker rm -f "$judge_container" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

# Reap judge containers from canceled jobs on this node. Docker is outside the
# Slurm cgroup, so an interrupted allocation can otherwise leave a GPU process.
mapfile -t stale_judges < <(sudo -n docker ps --filter name=physics-judge- --format '{{.Names}}')
for stale_judge in "${stale_judges[@]}"; do
    stale_job=${stale_judge##*-}
    if [[ "$stale_job" =~ ^[0-9]+$ ]] && [[ -z "$(squeue -h -j "$stale_job")" ]]; then
        sudo -n docker rm -f "$stale_judge" >/dev/null
    fi
done

{
    echo "job_id=$SLURM_JOB_ID"
    echo "node=$(hostname)"
    echo "judge_model=$judge_model"
    echo "mode=$mode"
    echo "judge_gpus=$judge_gpus"
    echo "judge_data_parallel_size=$judge_dp"
    echo "judge_tensor_parallel_size=$judge_tp"
    echo "trainer_gpus=$trainer_gpus"
    echo "started_at=$(date -Is)"
} | tee "$run_root/allocation.txt"
rocm-smi --showproductname --showmeminfo vram >"$run_root/gpus.txt" 2>&1

for image in "$judge_image" "$trainer_image"; do
    if ! sudo -n docker image inspect "$image" >/dev/null 2>&1; then
        sudo -n docker pull "$image"
    fi
done
cleanup

# Four independent model replicas maximize request throughput. Prefix caching,
# chunked prefill, a large scheduler batch, and graph execution keep the judge
# saturated by the concurrent reward workers.
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
    --env "CUDA_VISIBLE_DEVICES=$judge_gpus" \
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
    --reasoning-parser qwen3 \
    --reasoning-config '{"reasoning_start_str":"<think>","reasoning_end_str":"I have to give the solution based on the reasoning directly now.</think>"}' \
    --trust-remote-code \
    >"$run_root/judge-container-id.txt"

sudo -n docker logs --follow "$judge_container" >"$run_root/judge-vllm.log" 2>&1 &
judge_logger_pid=$!
ready=0
for _ in $(seq 1 240); do
    if sudo -n docker inspect --format '{{.State.Running}}' "$judge_container" 2>/dev/null | grep -qx true && \
        sudo -n docker logs "$judge_container" >"$run_root/judge-startup.pending.log" 2>&1 && \
        grep -q 'Application startup complete' "$run_root/judge-startup.pending.log" && \
        curl --fail --silent "http://127.0.0.1:$judge_port/v1/models" >"$run_root/models.pending.json"; then
        if python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(not any(x.get("id")==sys.argv[2] for x in d.get("data",[])))' \
            "$run_root/models.pending.json" "$judge_model"; then
            mv "$run_root/models.pending.json" "$run_root/models.json"
            ready=1
            break
        fi
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
python3 -m rlvr.smoke_llm_judge --requests 16 | tee "$run_root/judge-healthcheck.json"
date -Is >"$run_root/judge-ready.txt"

if [[ "$mode" == "serve" ]]; then
    endpoint="http://$(hostname):$judge_port/v1"
    echo "$endpoint" | tee "$run_root/endpoint.txt"
    echo "Judge server will remain active until this allocation is canceled or expires." \
        | tee "$run_root/server-status.txt"
    while true; do
        sleep 60
        curl --fail --silent "http://127.0.0.1:$judge_port/v1/models" >/dev/null
        date -Is >"$run_root/last-healthcheck.txt"
    done
fi

if [[ "$mode" == "evaluate" ]]; then
    sympy_validation="$repo_root/rlvr/runs/qwen3-4b-prism-grpo-train-20260902T193745Z-20379/validation"
    llm_validation="$repo_root/rlvr/runs/llm-judge-train-20403/training/validation"
    python3 -m rlvr.evaluate_checkpoint_rewards \
        --run "sympy_trained=$sympy_validation" \
        --truth-dir "$llm_validation" \
        --cache "$repo_root/rlvr/runs/analysis/sympy-checkpoints-binary-llm-cache.jsonl" \
        --output "$repo_root/rlvr/runs/analysis/sympy-checkpoint-binary-rewards.csv" \
        --native-workers 2 \
        --llm-workers 16 \
        2>&1 | tee "$run_root/checkpoint-evaluation.log"
    date -Is >"$run_root/completed.txt"
    exit 0
fi

case "$mode" in
    smoke)
        train_max_samples=${TRAIN_MAX_SAMPLES:-32}
        val_max_samples=${VAL_MAX_SAMPLES:-4}
        max_response_length=${MAX_RESPONSE_LENGTH:-1024}
        total_epochs=${TOTAL_EPOCHS:-1}
        save_freq=${SAVE_FREQ:--1}
        test_freq=${TEST_FREQ:--1}
        total_training_steps=${TOTAL_TRAINING_STEPS:-1}
        ;;
    train)
        train_max_samples=${TRAIN_MAX_SAMPLES:--1}
        val_max_samples=${VAL_MAX_SAMPLES:--1}
        max_response_length=${MAX_RESPONSE_LENGTH:-4096}
        total_epochs=${TOTAL_EPOCHS:-5}
        save_freq=${SAVE_FREQ:-10}
        test_freq=${TEST_FREQ:-10}
        total_training_steps=${TOTAL_TRAINING_STEPS:-}
        ;;
    *)
        echo "RLVR_MODE must be smoke or train, got: $mode" >&2
        exit 2
        ;;
esac

docker_env=(
    --env "CUDA_VISIBLE_DEVICES=$trainer_gpus"
    --env "WANDB_API_KEY=$WANDB_API_KEY"
    --env "WANDB_PROJECT=${WANDB_PROJECT:-physics-rlvr}"
    --env REWARD_TYPE=llm_judge
    --env "RLVR_MODE=$mode"
    --env TRAIN_DATASET=prism
    --env VALIDATION_DATASET=ugphysics
    --env "NGPUS_PER_NODE=$train_ngpus"
    --env "SLURM_JOB_ID=$SLURM_JOB_ID"
    --env "LLM_JUDGE_BASE_URL=$LLM_JUDGE_BASE_URL"
    --env "LLM_JUDGE_MODEL=$judge_model"
    --env "LLM_JUDGE_MAX_TOKENS=$LLM_JUDGE_MAX_TOKENS"
    --env "LLM_JUDGE_RETRIES=$LLM_JUDGE_RETRIES"
    # RemoteRewardManager creates N loop actors and N request actors per loop,
    # so N=8 yields 64 simultaneous HTTP requests without starving Ray of CPUs.
    --env REWARD_NUM_WORKERS=8
    --env REWARD_TIMEOUT_SECONDS=180
    --env TRAIN_BATCH_SIZE=16
    --env PPO_MINI_BATCH_SIZE=16
    --env ROLLOUT_N=4
    --env "TRAIN_MAX_SAMPLES=$train_max_samples"
    --env "VAL_MAX_SAMPLES=$val_max_samples"
    --env "MAX_RESPONSE_LENGTH=$max_response_length"
    --env "TOTAL_EPOCHS=$total_epochs"
    --env "SAVE_FREQ=$save_freq"
    --env "TEST_FREQ=$test_freq"
    --env "RLVR_RUN_ROOT=/workspace/physics/rlvr/runs/$run_name/training"
    --env "EXPERIMENT_NAME=qwen3-4b-prism-llm-judge-$mode-$SLURM_JOB_ID"
    --env HF_HUB_OFFLINE=1
    --env TRANSFORMERS_OFFLINE=1
)
if [[ -n "$total_training_steps" ]]; then
    docker_env+=(--env "TOTAL_TRAINING_STEPS=$total_training_steps")
fi

sudo -n docker run --rm \
    --name "$trainer_container" \
    --network host \
    --ipc host \
    --device=/dev/kfd \
    --device=/dev/dri \
    --group-add=video \
    --cap-add=SYS_PTRACE \
    --security-opt seccomp=unconfined \
    --ulimit memlock=-1 \
    --ulimit stack=67108864 \
    --shm-size=512g \
    --volume "$repo_root:/workspace/physics" \
    --volume /shared/data/home/aa3242/.cache/huggingface:/root/.cache/huggingface \
    --workdir /workspace/physics/verl \
    "${docker_env[@]}" \
    "$trainer_image" \
    /bin/bash -lc 'exec /bin/bash /workspace/physics/rlvr/train_qwen3_4b.sh' \
    2>&1 | tee "$run_root/trainer.log"

date -Is >"$run_root/completed.txt"
sudo -n docker rm -f "$judge_container" >/dev/null 2>&1 || true
wait "$judge_logger_pid" || true
