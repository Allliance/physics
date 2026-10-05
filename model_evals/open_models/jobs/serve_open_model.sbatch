#!/usr/bin/env bash
#SBATCH --partition=amd-mi355x
#SBATCH --exclude=mi355-gpu-11,mi355-gpu-35
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:8
#SBATCH --cpus-per-task=256
#SBATCH --mem=2900000M
#SBATCH --time=24:00:00
#SBATCH --signal=B:TERM@120
#SBATCH --output=/shared/data/home/aa3242/physics/model_evals/open_models/slurm/%x-%j.out
#SBATCH --error=/shared/data/home/aa3242/physics/model_evals/open_models/slurm/%x-%j.err

set -euo pipefail

eval_key=${EVAL_KEY:?EVAL_KEY must be glm or deepseek}
repo=/shared/data/home/aa3242/physics
cache=/shared/data/home/aa3242/.cache/huggingface
port=${MODEL_PORT:-8000}

case "$eval_key" in
    glm)
        model=zai-org/GLM-5.3
        tag=glm-5.3-max-no-tools-20260917
        image=${MODEL_VLLM_IMAGE:-vllm/vllm-openai-rocm:nightly}
        ;;
    deepseek)
        model=deepseek-ai/DeepSeek-V4-Pro
        tag=deepseek-v4-pro-max-no-tools-20260917
        image=${MODEL_VLLM_IMAGE:-vllm/vllm-openai-rocm:nightly-eed1f3d0c6043bd494424a22443ee198dd56f657}
        ;;
    *)
        echo "Unknown EVAL_KEY=$eval_key" >&2
        exit 2
        ;;
esac

container=${eval_key}-vllm-${SLURM_JOB_ID}
run="$repo/model_evals/$eval_key/runs/server-${SLURM_JOB_ID}"
suite="$repo/model_evals/$eval_key/runs/$tag"
mkdir -p "$run" "$suite" "$cache"

if python3 - "$suite/suite-summary.json" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
raise SystemExit(0 if path.exists() and json.loads(path.read_text()).get("complete") else 1)
PY
then
    echo "$model suite is already complete; no server startup needed."
    exit 0
fi

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
    echo "tensor_parallel_size=8"
    echo "reasoning_effort=max"
    echo "client_workers=8"
    echo "parallel_benchmark_jobs=17"
} >"$run/allocation.txt"
rocm-smi --showproductname >"$run/gpus.txt" 2>&1

if ! sudo -n docker image inspect "$image" >/dev/null 2>&1; then
    sudo -n docker pull "$image"
fi
while read -r stale; do
    [[ -n "$stale" ]] && sudo -n docker rm -f "$stale" >/dev/null
done < <(sudo -n docker ps -aq --filter "name=^${eval_key}-vllm-")
sudo -n docker rm -f "$container" >/dev/null 2>&1 || true

common=(
    serve "$model"
    --host 0.0.0.0
    --port "$port"
    --served-model-name "$model"
    --tensor-parallel-size 8
    --max-model-len 131072
    --max-num-batched-tokens 8192
    --trust-remote-code
)
if [[ "$eval_key" == glm ]]; then
    model_args=(
        --kv-cache-dtype fp8_e4m3
        --max-num-seqs 128
        --gpu-memory-utilization 0.80
        --speculative-config '{"method":"mtp","num_speculative_tokens":5}'
        --reasoning-parser glm45
        --tool-call-parser glm47
        --enable-auto-tool-choice
        --linear-backend aiter
        --moe-backend aiter
    )
    docker_env=(
        --env VLLM_ROCM_USE_AITER=1
        --env VLLM_ROCM_USE_AITER_FUSION_SHARED_EXPERTS=1
        --env VLLM_ENGINE_READY_TIMEOUT_S=43200
    )
else
    model_args=(
        --dtype auto
        --kv-cache-dtype fp8
        --max-num-seqs 512
        --distributed-executor-backend mp
        --gpu-memory-utilization 0.90
        --tokenizer-mode deepseek_v4
        --reasoning-parser deepseek_v4
        --tool-call-parser deepseek_v4
        --enable-auto-tool-choice
        --moe-backend aiter
        --async-scheduling
        --compilation-config '{"mode":3,"cudagraph_mode":"FULL_AND_PIECEWISE"}'
    )
    docker_env=(
        --env VLLM_ROCM_USE_AITER=1
        --env VLLM_ROCM_QUICK_REDUCE_QUANTIZATION=INT4
        --env VLLM_ROCM_USE_AITER_MOE=1
        --env VLLM_ROCM_USE_AITER_FUSION_SHARED_EXPERTS=0
        --env VLLM_ENGINE_READY_TIMEOUT_S=43200
        --env VLLM_PREFIX_CACHE_RETENTION_INTERVAL=32768
    )
fi

sudo -n docker run --detach \
    --name "$container" \
    --network host \
    --ipc host \
    --device=/dev/kfd \
    --device=/dev/dri \
    --group-add=video \
    --cap-add=SYS_PTRACE \
    --security-opt seccomp=unconfined \
    --volume "$cache:/root/.cache/huggingface" \
    "${docker_env[@]}" \
    --entrypoint /usr/local/bin/vllm \
    "$image" "${common[@]}" "${model_args[@]}" >"$run/container-id.txt"

sudo -n docker logs --follow "$container" >"$run/vllm.log" 2>&1 &
ready=0
for _ in $(seq 1 4320); do
    if curl --fail --silent "http://127.0.0.1:${port}/v1/models" >"$run/models.pending.json"; then
        mv "$run/models.pending.json" "$run/models.json"
        ready=1
        break
    fi
    if ! sudo -n docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null | grep -qx true; then
        sudo -n docker logs "$container" >&2 || true
        exit 1
    fi
    sleep 10
done
[[ "$ready" == 1 ]] || { echo "vLLM startup did not complete within 12 hours" >&2; exit 1; }

cat >"$run/endpoint.json" <<EOF
{
  "job_id": "$SLURM_JOB_ID",
  "node": "$(hostname)",
  "base_url": "http://$(hostname):${port}/v1",
  "model": "$model",
  "reasoning_effort": "max",
  "tensor_parallel_size": 8,
  "max_model_len": 131072
}
EOF
date -Is >"$run/ready.txt"
ln -sfn "server-${SLURM_JOB_ID}" "$repo/model_evals/$eval_key/runs/current-server"

set +e
bash "$repo/model_evals/open_models/jobs/run_when_ready.sh" "$SLURM_JOB_ID"
suite_code=$?
set -e
printf '%s\n' "$suite_code" >"$suite/last-exit-code.txt"
date -Is >"$suite/last-allocation-finished.txt"
exit "$suite_code"
