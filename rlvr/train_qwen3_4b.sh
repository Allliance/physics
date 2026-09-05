#!/usr/bin/env bash

set -euo pipefail

repo_root=${REPO_ROOT:-/workspace/physics}
verl_root="$repo_root/verl"
mode=${RLVR_MODE:-train}
val_only=${VAL_ONLY:-false}
train_dataset=${TRAIN_DATASET:-prism}
validation_dataset=${VALIDATION_DATASET:-ugphysics}
model_path=${MODEL_PATH:-Qwen/Qwen3-4B}
data_root=${RLVR_DATA_ROOT:-$repo_root/rlvr/data}

train_file="$data_root/$train_dataset/train.parquet"
validation_file="$data_root/$validation_dataset/validation.parquet"
reward_type=${REWARD_TYPE:-native}
resume_mode=${RESUME_MODE:-auto}
resume_from_path=${RESUME_FROM_PATH:-}
if [[ "$resume_mode" == resume_path && -z "$resume_from_path" ]]; then
    echo "RESUME_FROM_PATH is required when RESUME_MODE=resume_path" >&2
    exit 2
fi
case "$reward_type" in
    native)
        reward_path="$repo_root/rlvr/reward.py"
        ;;
    llm_judge)
        reward_path="$repo_root/rlvr/llm_judge_reward.py"
        ;;
    binary_llm_judge)
        reward_path="$repo_root/rlvr/binary_llm_judge_reward.py"
        ;;
    native_train_llm_validation)
        reward_path="$repo_root/rlvr/rule_train_binary_val_reward.py"
        ;;
    *)
        echo "REWARD_TYPE must be native, llm_judge, binary_llm_judge, or native_train_llm_validation, got: $reward_type" >&2
        exit 2
        ;;
esac
for required in "$train_file" "$validation_file" "$reward_path"; do
    if [[ ! -f "$required" ]]; then
        echo "Required RLVR input does not exist: $required" >&2
        exit 2
    fi
done

case "$mode" in
    smoke)
        train_batch_size=${TRAIN_BATCH_SIZE:-8}
        ppo_mini_batch_size=${PPO_MINI_BATCH_SIZE:-8}
        rollout_n=${ROLLOUT_N:-2}
        max_prompt_length=${MAX_PROMPT_LENGTH:-2048}
        max_response_length=${MAX_RESPONSE_LENGTH:-512}
        train_max_samples=${TRAIN_MAX_SAMPLES:-16}
        val_max_samples=${VAL_MAX_SAMPLES:-2}
        total_epochs=${TOTAL_EPOCHS:-1}
        total_training_steps=${TOTAL_TRAINING_STEPS:-1}
        save_freq=${SAVE_FREQ:--1}
        test_freq=${TEST_FREQ:--1}
        reward_num_workers=${REWARD_NUM_WORKERS:-1}
        ;;
    train)
        train_batch_size=${TRAIN_BATCH_SIZE:-16}
        ppo_mini_batch_size=${PPO_MINI_BATCH_SIZE:-16}
        rollout_n=${ROLLOUT_N:-4}
        max_prompt_length=${MAX_PROMPT_LENGTH:-2048}
        max_response_length=${MAX_RESPONSE_LENGTH:-4096}
        train_max_samples=${TRAIN_MAX_SAMPLES:--1}
        val_max_samples=${VAL_MAX_SAMPLES:--1}
        total_epochs=${TOTAL_EPOCHS:-5}
        total_training_steps=${TOTAL_TRAINING_STEPS:-}
        save_freq=${SAVE_FREQ:-10}
        test_freq=${TEST_FREQ:-10}
        reward_num_workers=${REWARD_NUM_WORKERS:-4}
        ;;
    *)
        echo "RLVR_MODE must be smoke or train, got: $mode" >&2
        exit 2
        ;;
esac

ngpus=${NGPUS_PER_NODE:-8}
project_name=${WANDB_PROJECT:-physics-rlvr}
trainer_logger=${TRAINER_LOGGER:-'["console","wandb"]'}
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
experiment_name=${EXPERIMENT_NAME:-qwen3-4b-${train_dataset}-grpo-${mode}-${timestamp}-${SLURM_JOB_ID:-local}}
run_root=${RLVR_RUN_ROOT:-$repo_root/rlvr/runs/$experiment_name}
mkdir -p "$run_root/checkpoints" "$run_root/validation" "$run_root/hydra"

export PYTHONPATH="$repo_root:$verl_root${PYTHONPATH:+:$PYTHONPATH}"
export HF_HUB_OFFLINE=${HF_HUB_OFFLINE:-1}
export TRANSFORMERS_OFFLINE=${TRANSFORMERS_OFFLINE:-1}
export TOKENIZERS_PARALLELISM=false
export NCCL_DEBUG=${NCCL_DEBUG:-WARN}
export HSA_ENABLE_IPC_MODE_LEGACY=${HSA_ENABLE_IPC_MODE_LEGACY:-1}
export PYTORCH_ALLOC_CONF=${PYTORCH_ALLOC_CONF:-expandable_segments:True}

trainer_steps=()
if [[ -n "$total_training_steps" ]]; then
    trainer_steps+=("trainer.total_training_steps=$total_training_steps")
fi
trainer_resume=("trainer.resume_mode=$resume_mode")
if [[ -n "$resume_from_path" ]]; then
    trainer_resume+=("trainer.resume_from_path=$resume_from_path")
fi

cat >"$run_root/launch.env" <<EOF
mode=$mode
model_path=$model_path
train_dataset=$train_dataset
validation_dataset=$validation_dataset
train_file=$train_file
validation_file=$validation_file
train_batch_size=$train_batch_size
ppo_mini_batch_size=$ppo_mini_batch_size
rollout_n=$rollout_n
max_prompt_length=$max_prompt_length
max_response_length=$max_response_length
ngpus=$ngpus
project_name=$project_name
trainer_logger=$trainer_logger
experiment_name=$experiment_name
prism_isolate=${RLVR_PRISM_ISOLATE:-1}
prism_max_memory_gb=${RLVR_PRISM_MAX_MEMORY_GB:-8}
reward_timeout_seconds=${REWARD_TIMEOUT_SECONDS:-20}
reward_type=$reward_type
reward_path=$reward_path
llm_judge_base_url=${LLM_JUDGE_BASE_URL:-}
llm_judge_model=${LLM_JUDGE_MODEL:-}
started_at=$(date -Is)
val_only=$val_only
resume_mode=$resume_mode
resume_from_path=$resume_from_path
EOF

cd "$verl_root"
python3 -m verl.trainer.main_ppo \
    hydra.run.dir="$run_root/hydra" \
    +ray_kwargs.ray_init.include_dashboard=False \
    +ray_kwargs.ray_init.object_store_memory="${RAY_OBJECT_STORE_MEMORY_BYTES:-20000000000}" \
    algorithm.adv_estimator=grpo \
    algorithm.use_kl_in_reward=False \
    data.train_files="$train_file" \
    data.val_files="$validation_file" \
    data.train_batch_size="$train_batch_size" \
    data.train_max_samples="$train_max_samples" \
    data.val_max_samples="$val_max_samples" \
    data.max_prompt_length="$max_prompt_length" \
    data.max_response_length="$max_response_length" \
    data.filter_overlong_prompts=True \
    data.filter_overlong_prompts_workers=8 \
    data.truncation=error \
    +data.apply_chat_template_kwargs.enable_thinking=True \
    actor_rollout_ref.model.path="$model_path" \
    actor_rollout_ref.model.use_remove_padding=True \
    actor_rollout_ref.model.enable_gradient_checkpointing=True \
    actor_rollout_ref.actor.optim.lr="${ACTOR_LR:-1e-6}" \
    actor_rollout_ref.actor.ppo_mini_batch_size="$ppo_mini_batch_size" \
    actor_rollout_ref.actor.use_dynamic_bsz=True \
    actor_rollout_ref.actor.ppo_max_token_len_per_gpu="${PPO_MAX_TOKEN_LEN_PER_GPU:-8192}" \
    actor_rollout_ref.actor.use_kl_loss=True \
    actor_rollout_ref.actor.kl_loss_coef="${KL_LOSS_COEF:-0.001}" \
    actor_rollout_ref.actor.kl_loss_type=low_var_kl \
    actor_rollout_ref.actor.entropy_coeff="${ENTROPY_COEFF:-0}" \
    actor_rollout_ref.actor.fsdp_config.param_offload=False \
    actor_rollout_ref.actor.fsdp_config.optimizer_offload=False \
    actor_rollout_ref.rollout.name=vllm \
    actor_rollout_ref.rollout.mode=async \
    actor_rollout_ref.rollout.tensor_model_parallel_size=1 \
    actor_rollout_ref.rollout.gpu_memory_utilization="${ROLLOUT_GPU_MEM_UTIL:-0.55}" \
    actor_rollout_ref.rollout.enforce_eager=True \
    actor_rollout_ref.rollout.free_cache_engine=True \
    actor_rollout_ref.rollout.n="$rollout_n" \
    actor_rollout_ref.rollout.temperature="${ROLLOUT_TEMPERATURE:-0.7}" \
    actor_rollout_ref.rollout.top_p="${ROLLOUT_TOP_P:-0.95}" \
    actor_rollout_ref.rollout.top_k="${ROLLOUT_TOP_K:-20}" \
    actor_rollout_ref.rollout.log_prob_use_dynamic_bsz=True \
    actor_rollout_ref.rollout.log_prob_max_token_len_per_gpu="${LOG_PROB_MAX_TOKEN_LEN_PER_GPU:-8192}" \
    +actor_rollout_ref.rollout.engine_kwargs.vllm.disable_custom_all_reduce=True \
    actor_rollout_ref.ref.log_prob_use_dynamic_bsz=True \
    actor_rollout_ref.ref.log_prob_max_token_len_per_gpu="${REF_LOG_PROB_MAX_TOKEN_LEN_PER_GPU:-8192}" \
    actor_rollout_ref.ref.fsdp_config.param_offload=False \
    reward.custom_reward_function.path="$reward_path" \
    reward.custom_reward_function.name=compute_score \
    +reward.custom_reward_function.reward_kwargs.timeout_seconds="${REWARD_TIMEOUT_SECONDS:-20}" \
    reward.reward_manager.name=remote \
    reward.num_workers="$reward_num_workers" \
    trainer.logger="$trainer_logger" \
    trainer.project_name="$project_name" \
    trainer.experiment_name="$experiment_name" \
    trainer.n_gpus_per_node="$ngpus" \
    trainer.nnodes=1 \
    trainer.total_epochs="$total_epochs" \
    trainer.save_freq="$save_freq" \
    trainer.test_freq="$test_freq" \
    trainer.val_before_train=True \
    trainer.val_only="$val_only" \
    trainer.log_val_generations="${LOG_VAL_GENERATIONS:-2}" \
    trainer.validation_data_dir="$run_root/validation" \
    trainer.default_local_dir="$run_root/checkpoints" \
    "${trainer_resume[@]}" \
    "${trainer_steps[@]}" \
    "$@"
