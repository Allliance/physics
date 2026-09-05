#!/usr/bin/env bash

#SBATCH --job-name=qwen3-4b-ckpt-comparison
#SBATCH --partition=amd-mi355x
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=96
#SBATCH --mem=1200000M
#SBATCH --time=08:00:00
#SBATCH --output=/shared/data/home/aa3242/physics/rlvr/runs/comparison-ugphysics-200/slurm/comparison-%j.out
#SBATCH --error=/shared/data/home/aa3242/physics/rlvr/runs/comparison-ugphysics-200/slurm/comparison-%j.err

set -euo pipefail

repo_root=/shared/data/home/aa3242/physics
comparison_root="$repo_root/rlvr/runs/comparison-ugphysics-200"
endpoint_file="$repo_root/llm_judge/server_runs/20509/endpoint.json"
steps=(20 40 60 80 100)
judge_pids=()
judge_labels=()
judge_failed=0

mkdir -p "$comparison_root/slurm" "$comparison_root/judgments"
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

run_judge() {
    local input=$1
    local output=$2
    local label=$3
    local status=1
    local attempt
    for attempt in 1 2 3 4 5 6 7 8 9 10; do
        echo "[$label] binary judge attempt $attempt"
        status=0
        PYTHONDONTWRITEBYTECODE=1 python3 -m rlvr.evaluate_binary \
            "$input" "$output" \
            --backend openai \
            --model "$judge_model" \
            --base-url "$judge_base_url" \
            --api-key EMPTY \
            --max-tokens 8192 \
            --temperature 0.6 \
            --top-p 0.95 \
            --extra-body '{"chat_template_kwargs":{"enable_thinking":true},"thinking_token_budget":4096,"top_k":20,"min_p":0.0}' \
            --workers 100 \
            --timeout 600 \
            --errors-as-zero \
            || status=$?
        if [[ "$status" -eq 0 ]]; then
            return 0
        fi
    done
    return "$status"
}

wait_oldest_judge() {
    local pid=${judge_pids[0]}
    local label=${judge_labels[0]}
    if ! wait "$pid"; then
        echo "Binary judge failed after retries: $label" >&2
        judge_failed=1
    fi
    judge_pids=("${judge_pids[@]:1}")
    judge_labels=("${judge_labels[@]:1}")
}

for step in "${steps[@]}"; do
    for training_reward in sympy llm_judge; do
        if [[ "$training_reward" == sympy ]]; then
            checkpoint_root="$repo_root/rlvr/runs/qwen3-4b-prism-grpo-train-20260902T193745Z-20379/checkpoints"
        else
            checkpoint_root="$repo_root/rlvr/runs/llm-judge-train-20403/training/checkpoints"
        fi
        checkpoint="$checkpoint_root/global_step_$step"
        run_root="$comparison_root/generations/${training_reward}_trained/step_$step"
        generation_file="$run_root/validation/$step.jsonl"
        judgment_file="$comparison_root/judgments/${training_reward}_trained/step_$step.jsonl"
        label="${training_reward}-trained-step-$step"

        if [[ ! -d "$checkpoint/actor" ]]; then
            echo "Checkpoint actor directory is missing: $checkpoint/actor" >&2
            exit 2
        fi
        generation_rows=0
        if [[ -f "$generation_file" ]]; then
            generation_rows=$(wc -l <"$generation_file")
        fi
        if [[ "$generation_rows" -ne 200 ]]; then
            echo "[$label] generating 200 UGPhysics responses"
            export RLVR_MODE=smoke
            export VAL_ONLY=true
            export TRAIN_DATASET=prism
            export VALIDATION_DATASET=ugphysics
            export REWARD_TYPE=native
            export RLVR_NGPUS=4
            export ROLLOUT_N=1
            export VAL_MAX_SAMPLES=-1
            export MAX_RESPONSE_LENGTH=2048
            export LOG_VAL_GENERATIONS=0
            # verl creates this many reward actors per each of 8 agent-loop
            # workers. Four gives 32-way scoring without exhausting 256 CPUs.
            export REWARD_NUM_WORKERS=4
            export REWARD_TIMEOUT_SECONDS=60
            export RESUME_MODE=resume_path
            export RESUME_FROM_PATH=${checkpoint/$repo_root/\/workspace\/physics}
            export RLVR_RUN_ROOT=${run_root/$repo_root/\/workspace\/physics}
            export EXPERIMENT_NAME="qwen3-4b-$label"
            export TRAINER_LOGGER='["console"]'
            /bin/bash "$repo_root/rlvr/jobs/qwen3_4b.sbatch"
            generation_rows=$(wc -l <"$generation_file")
            if [[ "$generation_rows" -ne 200 ]]; then
                echo "[$label] generated $generation_rows rows, expected 200" >&2
                exit 1
            fi
        else
            echo "[$label] reusing complete 200-row generation file"
        fi

        summary_file=${judgment_file%.jsonl}.summary.json
        judge_complete=0
        if [[ -f "$summary_file" ]]; then
            judge_complete=$(python3 - "$summary_file" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))
print(int(value.get("num_completed") == 200 and value.get("num_judge_errors") == 0))
PY
)
        fi
        if [[ "$judge_complete" -eq 0 ]]; then
            mkdir -p "$(dirname "$judgment_file")"
            run_judge "$generation_file" "$judgment_file" "$label" \
                >"$comparison_root/slurm/judge-$label.log" 2>&1 &
            judge_pids+=("$!")
            judge_labels+=("$label")
            # Two judge processes x 100 workers = 200 concurrent requests,
            # below the existing server's 256-sequence capacity.
            if (( ${#judge_pids[@]} >= 2 )); then
                wait_oldest_judge
            fi
        else
            echo "[$label] reusing complete binary judgments"
        fi
    done
done

while (( ${#judge_pids[@]} > 0 )); do
    wait_oldest_judge
done
if [[ "$judge_failed" -ne 0 ]]; then
    exit 1
fi

/shared/data/home/aa3242/.local/bin/uv run --with matplotlib \
    python -m rlvr.summarize_checkpoint_comparison
echo "Comparison complete: $comparison_root/checkpoint_scores.png"
