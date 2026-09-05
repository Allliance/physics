#!/usr/bin/env bash

#SBATCH --job-name=qwen3-4b-prism-ood-final
#SBATCH --partition=amd-mi355x
#SBATCH --exclude=mi355-gpu-11
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=128
#SBATCH --mem=1400000M
#SBATCH --time=06:00:00
#SBATCH --output=/shared/data/home/aa3242/physics/rlvr/runs/slurm/%x-%j.out
#SBATCH --error=/shared/data/home/aa3242/physics/rlvr/runs/slurm/%x-%j.err

set -euo pipefail

repo_root=/shared/data/home/aa3242/physics
: "${TRAINING_RUN_ROOT:?TRAINING_RUN_ROOT must name the completed training run}"
: "${OOD_EVAL_LABEL:?OOD_EVAL_LABEL must identify the training reward}"

data_root=${RLVR_DATA_ROOT:-$repo_root/rlvr/data_ugphysics_gpt56_clean}
endpoint_file=${LLM_JUDGE_ENDPOINT_FILE:-$repo_root/llm_judge/server_runs/20585/endpoint.json}
checkpoint_root="$TRAINING_RUN_ROOT/checkpoints"
latest_file="$checkpoint_root/latest_checkpointed_iteration.txt"
eval_root="$TRAINING_RUN_ROOT/prism_ood_final"

if [[ ! -f "$latest_file" ]]; then
    echo "Latest-checkpoint marker is missing: $latest_file" >&2
    exit 2
fi
step=$(tr -d '[:space:]' <"$latest_file")
if [[ ! "$step" =~ ^[0-9]+$ ]]; then
    echo "Invalid checkpoint step in $latest_file: $step" >&2
    exit 2
fi
checkpoint="$checkpoint_root/global_step_$step"
if [[ ! -d "$checkpoint/actor" ]]; then
    echo "Checkpoint actor directory is missing: $checkpoint/actor" >&2
    exit 2
fi
if [[ ! -f "$endpoint_file" ]]; then
    echo "Judge endpoint metadata is missing: $endpoint_file" >&2
    exit 2
fi

readarray -t endpoint < <(
    python3 - "$endpoint_file" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))
print(value["base_url"])
print(value["model"])
PY
)
judge_base_url=${endpoint[0]}
judge_model=${endpoint[1]}
curl -fsS --max-time 10 "$judge_base_url/models" >/dev/null

mkdir -p "$eval_root"
generation_file="$eval_root/validation/$step.jsonl"
generation_rows=0
if [[ -f "$generation_file" ]]; then
    generation_rows=$(wc -l <"$generation_file")
fi
expected_rows=$(python3 - "$data_root/manifest.json" <<'PY'
import json
import sys

print(json.load(open(sys.argv[1], encoding="utf-8"))["prism_ood_validation_rows"])
PY
)

if [[ "$generation_rows" -ne "$expected_rows" ]]; then
    export RLVR_MODE=smoke
    export VAL_ONLY=true
    export TRAIN_DATASET=ugphysics
    export VALIDATION_DATASET=prism_ood
    export RLVR_DATA_ROOT=${data_root/$repo_root/\/workspace\/physics}
    export REWARD_TYPE=native
    export RLVR_NGPUS=4
    export ROLLOUT_N=1
    export VAL_MAX_SAMPLES=-1
    export MAX_RESPONSE_LENGTH=4096
    export LOG_VAL_GENERATIONS=0
    export REWARD_NUM_WORKERS=4
    export REWARD_TIMEOUT_SECONDS=180
    export RESUME_MODE=resume_path
    export RESUME_FROM_PATH=${checkpoint/$repo_root/\/workspace\/physics}
    export RLVR_RUN_ROOT=${eval_root/$repo_root/\/workspace\/physics}
    export EXPERIMENT_NAME="qwen3-4b-${OOD_EVAL_LABEL}-prism-ood-final"
    export TRAINER_LOGGER='["console"]'
    /bin/bash "$repo_root/rlvr/jobs/qwen3_4b.sbatch"
    generation_rows=$(wc -l <"$generation_file")
fi
if [[ "$generation_rows" -ne "$expected_rows" ]]; then
    echo "Generated $generation_rows PRISM rows, expected $expected_rows" >&2
    exit 1
fi

judgments="$eval_root/qwen35_judgments.jsonl"
for attempt in 1 2 3 4 5; do
    status=0
    PYTHONPATH="$repo_root" python3 -m rlvr.evaluate_binary \
        "$generation_file" "$judgments" \
        --backend openai \
        --model "$judge_model" \
        --base-url "$judge_base_url" \
        --api-key EMPTY \
        --max-tokens 8192 \
        --temperature 0.6 \
        --top-p 0.95 \
        --extra-body '{"chat_template_kwargs":{"enable_thinking":true},"thinking_token_budget":4096,"top_k":20,"min_p":0.0}' \
        --workers 64 \
        --timeout 600 \
        --strict-errors \
        || status=$?
    if [[ "$status" -eq 0 ]]; then
        date -Is >"$eval_root/completed.txt"
        exit 0
    fi
    echo "Qwen PRISM judgment attempt $attempt failed; resuming incomplete rows" >&2
done
exit "$status"
