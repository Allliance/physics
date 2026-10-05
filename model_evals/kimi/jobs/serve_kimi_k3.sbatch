#!/usr/bin/env bash
#SBATCH --job-name=kimi-k3-server
#SBATCH --partition=amd-mi355x
#SBATCH --exclude=mi355-gpu-11
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:8
#SBATCH --cpus-per-task=256
#SBATCH --mem=2900000M
#SBATCH --time=24:00:00
#SBATCH --signal=B:TERM@120
#SBATCH --output=/shared/data/home/aa3242/physics/model_evals/kimi/slurm/%x-%j.out
#SBATCH --error=/shared/data/home/aa3242/physics/model_evals/kimi/slurm/%x-%j.err

set -euo pipefail

repo=/shared/data/home/aa3242/physics
cache=/shared/data/home/aa3242/.cache/huggingface
image=${KIMI_VLLM_IMAGE:-vllm/vllm-openai-rocm:kimi-k3}
model=moonshotai/Kimi-K3
port=${KIMI_PORT:-8000}
container=kimi-k3-vllm-${SLURM_JOB_ID}
run="$repo/model_evals/kimi/runs/server-${SLURM_JOB_ID}"
suite="$repo/model_evals/kimi/runs/kimi-k3-max-no-tools-20260917"
mkdir -p "$run" "$cache"

if python3 - "$suite/suite-summary.json" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
raise SystemExit(0 if path.exists() and json.loads(path.read_text()).get("complete") else 1)
PY
then
    echo "Kimi suite is already complete; no server startup needed."
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
    echo "max_model_len=81920"
} >"$run/allocation.txt"
rocm-smi --showproductname >"$run/gpus.txt" 2>&1

if ! sudo -n docker image inspect "$image" >/dev/null 2>&1; then
    sudo -n docker pull "$image"
fi
while read -r stale; do
    [[ -n "$stale" ]] && sudo -n docker rm -f "$stale" >/dev/null
done < <(sudo -n docker ps -aq --filter 'name=^kimi-k3-vllm-')
sudo -n docker rm -f "$container" >/dev/null 2>&1 || true
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
    --env VLLM_ROCM_USE_AITER=1 \
    --env SAFETENSORS_FAST_GPU=1 \
    --env VLLM_ROCM_USE_AITER_MOE_SITUV2=1 \
    --env VLLM_ROCM_USE_AITER_MOE_SITUV2_A8W4=1 \
    --env VLLM_USE_BREAKABLE_CUDAGRAPH=0 \
    --entrypoint /usr/local/bin/vllm \
    "$image" serve "$model" \
    --host 0.0.0.0 \
    --port "$port" \
    --served-model-name "$model" \
    --tensor-parallel-size 8 \
    --max-model-len 81920 \
    --max-num-seqs 128 \
    --max-num-batched-tokens 4096 \
    --gpu-memory-utilization 0.95 \
    --load-format auto \
    --mm-encoder-tp-mode data \
    --reasoning-parser kimi_k3 \
    --compilation-config '{"cudagraph_mode":"FULL_DECODE_ONLY","custom_ops":["+fused_rms_norm_gated"]}' \
    --trust-remote-code >"$run/container-id.txt"

sudo -n docker logs --follow "$container" >"$run/vllm.log" 2>&1 &
logger_pid=$!
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
if [[ "$ready" != 1 ]]; then
    echo "Kimi vLLM startup did not complete within 12 hours" >&2
    exit 1
fi

cat >"$run/endpoint.json" <<EOF
{
  "job_id": "$SLURM_JOB_ID",
  "node": "$(hostname)",
  "base_url": "http://$(hostname):${port}/v1",
  "model": "$model",
  "reasoning_parser": "kimi_k3",
  "reasoning_effort": "max",
  "tensor_parallel_size": 8,
  "max_model_len": 81920
}
EOF
date -Is >"$run/ready.txt"
ln -sfn "server-${SLURM_JOB_ID}" "$repo/model_evals/kimi/runs/current-server"

cd "$repo"
set +e
bash model_evals/kimi/jobs/run_when_ready.sh "$SLURM_JOB_ID"
suite_code=$?
set -e
printf '%s\n' "$suite_code" >"$suite/last-exit-code.txt"
date -Is >"$suite/last-allocation-finished.txt"
exit "$suite_code"
