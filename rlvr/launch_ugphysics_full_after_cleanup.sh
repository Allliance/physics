#!/usr/bin/env bash
# Wait for cleanup, build final datasets, and submit the two full RLVR runs.

set -euo pipefail

repo_root=/shared/data/home/aa3242/physics
artifact="$repo_root/benchmarks/ugphysics/artifacts/gpt-5.6-sol-high-full-5520"
sample="$artifact/sample.jsonl"
generations="$artifact/generations.jsonl"
judgments="$artifact/qwen35_judgments.jsonl"
judgment_summary="$artifact/qwen35_judgments.summary.json"
audit="$repo_root/audit/all-responses/ugphysics/responses.jsonl"
data_root="$repo_root/rlvr/data_ugphysics_gpt56_clean"
endpoint_file="$repo_root/llm_judge/server_runs/20585/endpoint.json"
state_file="$repo_root/rlvr/runs/ugphysics-full-launch.json"
native_run="$repo_root/rlvr/runs/qwen3-4b-ug-gpt56-clean-native"
judge_run="$repo_root/rlvr/runs/qwen3-4b-ug-gpt56-clean-judge"

mkdir -p "$repo_root/rlvr/runs"
if [[ -f "$state_file" ]]; then
    echo "Full training jobs were already submitted; refusing to duplicate them: $state_file" >&2
    exit 2
fi
if [[ ! -f "$endpoint_file" ]]; then
    echo "Judge endpoint metadata is missing: $endpoint_file" >&2
    exit 2
fi

while true; do
    generation_rows=$(wc -l <"$generations")
    completed_judgments=0
    judge_errors=0
    if [[ -f "$judgment_summary" ]]; then
        readarray -t counts < <(
            python3 - "$judgment_summary" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))
print(value.get("completed_judgments", 0))
print(value.get("judge_errors", 0))
PY
        )
        completed_judgments=${counts[0]}
        judge_errors=${counts[1]}
    fi
    printf '%s generations=%s/5520 judgments=%s/4520 errors=%s\n' \
        "$(date -Is)" "$generation_rows" "$completed_judgments" "$judge_errors"
    if [[ "$generation_rows" -eq 5520 && "$completed_judgments" -eq 4520 && "$judge_errors" -eq 0 ]]; then
        break
    fi
    if [[ "$generation_rows" -lt 5520 ]] && ! tmux has-session -t ugphysics-full-cleanup 2>/dev/null; then
        echo "GPT cleanup process stopped before all generations completed" >&2
        exit 1
    fi
    if [[ "$completed_judgments" -lt 4520 ]] && ! tmux has-session -t ugphysics-cleanup-judge 2>/dev/null; then
        echo "Qwen cleanup judge stopped before all judgments completed" >&2
        exit 1
    fi
    sleep 30
done

/shared/data/home/aa3242/.local/bin/uv run --with pyarrow --with chardet \
    python -m rlvr.prepare_ugphysics_training_data \
    --audit "$audit" \
    --sample "$sample" \
    --judgments "$judgments" \
    --output-root "$data_root" \
    --seed 20260904 \
    --validation-fraction 0.1

python3 - "$data_root/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
counts = manifest["counts"]
assert counts["audited_seed_rows"] == 1000, counts
assert counts["seed_benchmark_failures_excluded"] == 330, counts
assert counts["seed_rows_kept"] == 670, counts
assert counts["new_rows_judged"] == 4520, counts
assert manifest["train_rows"] + manifest["validation_rows"] == counts["combined_rows"]
assert manifest["validation_rows"] == round(counts["combined_rows"] * 0.1)
assert manifest["prism_ood_validation_rows"] == 579, manifest
PY

common_exports="ALL,RLVR_MODE=train,RLVR_NGPUS=4,RLVR_DATA_ROOT=/workspace/physics/rlvr/data_ugphysics_gpt56_clean,TRAIN_DATASET=ugphysics,VALIDATION_DATASET=ugphysics,TRAIN_BATCH_SIZE=16,PPO_MINI_BATCH_SIZE=16,ROLLOUT_N=2,MAX_RESPONSE_LENGTH=4096,TOTAL_EPOCHS=1,SAVE_FREQ=100,TEST_FREQ=100"

native_job=$(
    sbatch --parsable \
        --job-name=qwen3-4b-ug-native-full \
        --exclude=mi355-gpu-11 \
        --gres=gpu:4 --cpus-per-task=128 --mem=1400000M --time=24:00:00 \
        --export="$common_exports,REWARD_TYPE=native,REWARD_NUM_WORKERS=4,REWARD_TIMEOUT_SECONDS=180,EXPERIMENT_NAME=qwen3-4b-ug-gpt56-clean-native,RLVR_RUN_ROOT=/workspace/physics/rlvr/runs/qwen3-4b-ug-gpt56-clean-native" \
        "$repo_root/rlvr/jobs/qwen3_4b.sbatch"
)

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
judge_job=$(
    sbatch --parsable \
        --job-name=qwen3-4b-ug-judge-full \
        --exclude=mi355-gpu-11 \
        --gres=gpu:4 --cpus-per-task=128 --mem=1400000M --time=24:00:00 \
        --export="$common_exports,REWARD_TYPE=binary_llm_judge,REWARD_NUM_WORKERS=8,REWARD_TIMEOUT_SECONDS=600,EXPERIMENT_NAME=qwen3-4b-ug-gpt56-clean-judge,RLVR_RUN_ROOT=/workspace/physics/rlvr/runs/qwen3-4b-ug-gpt56-clean-judge,LLM_JUDGE_BASE_URL=$judge_base_url,LLM_JUDGE_MODEL=$judge_model,LLM_JUDGE_MAX_TOKENS=8192,LLM_JUDGE_PARSE_RETRIES=3,LLM_JUDGE_BINARY_MAX_TOKENS=8192,LLM_JUDGE_BINARY_TEMPERATURE=0.6,LLM_JUDGE_BINARY_TOP_P=0.95,LLM_JUDGE_BINARY_TOP_K=20,LLM_JUDGE_BINARY_MIN_P=0.0,LLM_JUDGE_BINARY_THINKING_TOKEN_BUDGET=4096,LLM_JUDGE_RAISE_ERRORS=1" \
        "$repo_root/rlvr/jobs/qwen3_4b.sbatch"
)

native_ood_job=$(
    sbatch --parsable --dependency="afterok:$native_job" \
        --job-name=qwen3-4b-native-prism-final \
        --export="ALL,TRAINING_RUN_ROOT=$native_run,OOD_EVAL_LABEL=native,RLVR_DATA_ROOT=$data_root,LLM_JUDGE_ENDPOINT_FILE=$endpoint_file" \
        "$repo_root/rlvr/jobs/final_prism_ood_eval.sbatch"
)
judge_ood_job=$(
    sbatch --parsable --dependency="afterok:$judge_job" \
        --job-name=qwen3-4b-judge-prism-final \
        --export="ALL,TRAINING_RUN_ROOT=$judge_run,OOD_EVAL_LABEL=judge,RLVR_DATA_ROOT=$data_root,LLM_JUDGE_ENDPOINT_FILE=$endpoint_file" \
        "$repo_root/rlvr/jobs/final_prism_ood_eval.sbatch"
)

python3 - "$state_file" "$native_job" "$judge_job" "$native_ood_job" "$judge_ood_job" <<'PY'
from datetime import datetime, timezone
import json
import sys

path, native, judge, native_ood, judge_ood = sys.argv[1:]
value = {
    "submitted_at": datetime.now(timezone.utc).isoformat(),
    "training_order": ["native_sympy", "qwen_judge"],
    "native_training_job": native,
    "judge_training_job": judge,
    "native_final_prism_ood_job": native_ood,
    "judge_final_prism_ood_job": judge_ood,
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(value, handle, indent=2)
    handle.write("\n")
print(json.dumps(value, indent=2))
PY

jobs=("$native_job" "$judge_job" "$native_ood_job" "$judge_ood_job")
while true; do
    complete=0
    for job in "${jobs[@]}"; do
        state=$(sacct -n -X -j "$job" -o State --parsable2 | sed '/^[[:space:]]*$/d' | head -n 1 | tr -d '[:space:]')
        printf '%s job=%s state=%s\n' "$(date -Is)" "$job" "${state:-UNKNOWN}"
        case "$state" in
            COMPLETED)
                complete=$((complete + 1))
                ;;
            FAILED*|CANCELLED*|TIMEOUT*|OUT_OF_MEMORY*|NODE_FAIL*)
                echo "Monitored job $job entered terminal failure state $state" >&2
                exit 1
                ;;
        esac
    done
    if [[ "$complete" -eq "${#jobs[@]}" ]]; then
        echo "All UGPhysics training and final PRISM OOD jobs completed"
        exit 0
    fi
    sleep 60
done
