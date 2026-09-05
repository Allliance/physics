#!/usr/bin/env bash

#SBATCH --job-name=qwen3-4b-rlvr
#SBATCH --partition=amd-mi355x
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:8
#SBATCH --cpus-per-task=200
#SBATCH --mem=2900000M
#SBATCH --time=24:00:00
#SBATCH --output=/shared/data/home/aa3242/physics/rlvr/runs/slurm/%x-%j.out
#SBATCH --error=/shared/data/home/aa3242/physics/rlvr/runs/slurm/%x-%j.err

set -euo pipefail

repo_root=/shared/data/home/aa3242/physics
image=${VERL_ROCM_IMAGE:-amdagi/verl-dev:rocm7.14_torch2.12_release_0724}
mode=${RLVR_MODE:-train}
ngpus=${RLVR_NGPUS:-${SLURM_GPUS_ON_NODE:-8}}
container="physics-rlvr-${SLURM_JOB_ID}"
run_meta="$repo_root/rlvr/runs/slurm/$SLURM_JOB_ID"
ray_tmp="$run_meta/ray"
datasets_cache="$repo_root/rlvr/runs/.hf_datasets_cache"
wandb_root="$repo_root/rlvr/runs/.wandb"
trainer_logger=${TRAINER_LOGGER:-'["console","wandb"]'}
mkdir -p "$run_meta" "$ray_tmp" "$datasets_cache"

container_group_args=(--group-add=video)
container_ipc_args=(--ipc=host --shm-size=512g)
if sudo -n docker info >/dev/null 2>&1; then
    container_command=(sudo -n docker)
    container_runtime=docker
elif docker info >/dev/null 2>&1; then
    container_command=(docker)
    container_runtime=docker
elif command -v podman >/dev/null 2>&1; then
    # Keep each Slurm job's rootless Podman runtime metadata isolated. Multiple
    # RLVR allocations can share a node and otherwise race over runtime state.
    export XDG_RUNTIME_DIR=/tmp/physics-rlvr-runtime-$UID-${SLURM_JOB_ID}
    mkdir -p "$XDG_RUNTIME_DIR"
    chmod 700 "$XDG_RUNTIME_DIR"
    if ! podman info >/dev/null 2>&1; then
        echo "Podman is installed but unavailable for the current user on $(hostname)" >&2
        exit 1
    fi
    container_command=(podman)
    container_runtime=podman
    container_group_args=(--group-add=keep-groups)
    # Rootless Podman rejects --shm-size when joining the host IPC namespace.
    container_ipc_args=(--ipc=host)
else
    echo "No usable Docker or Podman runtime is available on $(hostname)" >&2
    exit 1
fi
container_image=$image
if [[ "$container_runtime" == podman && "$container_image" != *.*/* ]]; then
    container_image="docker.io/$container_image"
fi

use_wandb=false
if [[ "$trainer_logger" == *wandb* ]]; then
    use_wandb=true
    mkdir -p "$wandb_root/cache" "$wandb_root/config" "$wandb_root/runs"
    # The user's shell exports WANDB_TOKEN; W&B itself expects WANDB_API_KEY.
    set +u
    source /shared/data/home/aa3242/.bashrc
    set -u
    export WANDB_API_KEY=${WANDB_API_KEY:-${WANDB_TOKEN:-}}
    if [[ -z "$WANDB_API_KEY" ]]; then
        echo "WANDB_API_KEY/WANDB_TOKEN is not available after sourcing ~/.bashrc" >&2
        exit 2
    fi
fi

cleanup() {
    "${container_command[@]}" rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

{
    echo "job_id=$SLURM_JOB_ID"
    echo "node=$(hostname)"
    echo "mode=$mode"
    echo "ngpus=$ngpus"
    echo "image=$image"
    echo "container_runtime=$container_runtime"
    echo "started_at=$(date -Is)"
} | tee "$run_meta/allocation.txt"
rocm-smi --showproductname --showmeminfo vram >"$run_meta/gpus.txt" 2>&1

if ! "${container_command[@]}" image inspect "$container_image" >/dev/null 2>&1; then
    "${container_command[@]}" pull "$container_image"
fi
cleanup

docker_env=(
    --env "RLVR_MODE=$mode"
    --env "TRAIN_DATASET=${TRAIN_DATASET:-prism}"
    --env "VALIDATION_DATASET=${VALIDATION_DATASET:-ugphysics}"
    --env "NGPUS_PER_NODE=$ngpus"
    --env "SLURM_JOB_ID=$SLURM_JOB_ID"
    --env RLVR_REWARD_DEPS=/opt/physics-reward-deps
    --env "RLVR_PRISM_ISOLATE=${RLVR_PRISM_ISOLATE:-1}"
    --env "RLVR_PRISM_MAX_MEMORY_GB=${RLVR_PRISM_MAX_MEMORY_GB:-8}"
    --env HF_HUB_OFFLINE=1
    --env TRANSFORMERS_OFFLINE=1
    --env HF_DATASETS_CACHE=/workspace/physics/rlvr/runs/.hf_datasets_cache
)
if [[ "$use_wandb" == true ]]; then
    docker_env+=(
        --env "WANDB_API_KEY=$WANDB_API_KEY"
        --env "WANDB_PROJECT=${WANDB_PROJECT:-physics-rlvr}"
        --env WANDB_DIR=/workspace/physics/rlvr/runs/.wandb/runs
        --env WANDB_CACHE_DIR=/workspace/physics/rlvr/runs/.wandb/cache
        --env WANDB_CONFIG_DIR=/workspace/physics/rlvr/runs/.wandb/config
    )
fi
if [[ -n "${SLURM_JOB_GPUS:-}" ]]; then
    # Docker's daemon is outside Slurm's device cgroup, so select the physical
    # allocation explicitly. CUDA_VISIBLE_DEVICES is honored by ROCm; Ray then
    # propagates the physical allocation ID to each worker.
    docker_env+=(
        --env "CUDA_VISIBLE_DEVICES=$SLURM_JOB_GPUS"
    )
fi
for optional_name in EXPERIMENT_NAME MODEL_PATH RLVR_DATA_ROOT TRAIN_BATCH_SIZE PPO_MINI_BATCH_SIZE ROLLOUT_N \
    MAX_PROMPT_LENGTH MAX_RESPONSE_LENGTH TRAIN_MAX_SAMPLES VAL_MAX_SAMPLES TOTAL_EPOCHS \
    TOTAL_TRAINING_STEPS SAVE_FREQ TEST_FREQ ACTOR_LR KL_LOSS_COEF REWARD_NUM_WORKERS \
    REWARD_TIMEOUT_SECONDS RLVR_PRISM_MAX_ANSWER_EQUATIONS RLVR_RUN_ROOT VAL_ONLY REWARD_TYPE \
    RESUME_MODE RESUME_FROM_PATH LOG_VAL_GENERATIONS MODEL_PATH ROLLOUT_GPU_MEM_UTIL \
    ROLLOUT_TEMPERATURE ROLLOUT_TOP_P ROLLOUT_TOP_K TRAINER_LOGGER \
    LLM_JUDGE_BASE_URL LLM_JUDGE_MODEL LLM_JUDGE_MAX_TOKENS LLM_JUDGE_RETRIES \
    LLM_JUDGE_PARSE_RETRIES LLM_JUDGE_BINARY_MAX_TOKENS LLM_JUDGE_BINARY_TEMPERATURE \
    LLM_JUDGE_BINARY_TOP_P LLM_JUDGE_BINARY_TOP_K LLM_JUDGE_BINARY_MIN_P \
    LLM_JUDGE_BINARY_THINKING_TOKEN_BUDGET LLM_JUDGE_RAISE_ERRORS; do
    if [[ -n "${!optional_name:-}" ]]; then
        docker_env+=(--env "$optional_name=${!optional_name}")
    fi
done
for optional_name in WANDB_RUN_ID WANDB_RESUME; do
    if [[ -n "${!optional_name:-}" ]]; then
        docker_env+=(--env "$optional_name=${!optional_name}")
    fi
done

if [[ "${REWARD_TYPE:-native}" == "llm_judge" || \
      "${REWARD_TYPE:-native}" == "binary_llm_judge" || \
      "${REWARD_TYPE:-native}" == "native_train_llm_validation" ]]; then
    : "${LLM_JUDGE_BASE_URL:?LLM_JUDGE_BASE_URL is required for the LLM judge reward}"
    if ! curl --fail --silent --max-time 10 \
        "${LLM_JUDGE_BASE_URL%/}/models" >/dev/null; then
        echo "LLM judge endpoint is unavailable: $LLM_JUDGE_BASE_URL" >&2
        exit 1
    fi
fi

"${container_command[@]}" run --rm \
    --name "$container" \
    --network host \
    "${container_ipc_args[@]}" \
    --device=/dev/kfd \
    --device=/dev/dri \
    "${container_group_args[@]}" \
    --cap-add=SYS_PTRACE \
    --security-opt seccomp=unconfined \
    --ulimit memlock=-1 \
    --ulimit stack=67108864 \
    --volume "$repo_root:/workspace/physics" \
    --volume /shared/data/home/aa3242/.cache/huggingface:/root/.cache/huggingface \
    --volume "$ray_tmp:/tmp/ray" \
    --workdir /workspace/physics/verl \
    "${docker_env[@]}" \
    "$container_image" \
    /bin/bash -lc \
    'python3 -m pip install --disable-pip-version-check -q --target /opt/physics-reward-deps -r /workspace/physics/rlvr/reward-requirements.txt && exec /bin/bash /workspace/physics/rlvr/train_qwen3_4b.sh' \
    2>&1 | tee "$run_meta/container.log"
