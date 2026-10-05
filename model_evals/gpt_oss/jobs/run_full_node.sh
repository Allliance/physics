#!/usr/bin/env bash
set -euo pipefail

repo=/shared/data/home/aa3242/physics
image=${GPT_OSS_VLLM_IMAGE:-rocm/vllm:rocm7.13.0_gfx950-dcgpu_ubuntu24.04_py3.13_pytorch_2.10.0_vllm_0.19.1}
model=openai/gpt-oss-120b
port=8000
container=gpt-oss-120b-vllm-${SLURM_JOB_ID}
run="$repo/model_evals/gpt_oss/runs/gpt-oss-120b-high-no-tools-corrected-20260914"
tools_run="$repo/model_evals/gpt_oss/runs/gpt-oss-120b-high-tools-corrected-20260914"
mkdir -p "$run"

proxy_pid=
cleanup() {
  [[ -n "$proxy_pid" ]] && kill "$proxy_pid" >/dev/null 2>&1 || true
  sudo -n docker rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

{
  echo "job_id=$SLURM_JOB_ID"
  echo "node=$(hostname)"
  echo "started_at=$(date -Is)"
  echo "image=$image"
  echo "model=$model"
  echo "reasoning_effort=high"
  echo "gpus=8"
  echo "data_parallel_size=8"
  echo "max_num_seqs=256"
  echo "gpu_memory_utilization=0.90"
  echo "attention_backend=TRITON_ATTN_after_gfx950_aiter_startup_fault"
  echo "async_scheduling=disabled"
  echo "expert_parallel=enabled"
  echo "all2all_backend=naive"
  echo "client_workers_per_benchmark=${GPT_OSS_CLIENT_WORKERS:-128}"
} > "$run/allocation.txt"
rocm-smi --showproductname > "$run/gpus.txt" 2>&1

if ! sudo -n docker image inspect "$image" >/dev/null 2>&1; then sudo -n docker pull "$image"; fi
sudo -n docker rm -f "$container" >/dev/null 2>&1 || true
sudo -n docker run --detach \
  --name "$container" --network host --ipc host \
  --device=/dev/kfd --device=/dev/dri --group-add=video \
  --cap-add=SYS_PTRACE --security-opt seccomp=unconfined \
  --volume /shared/data/home/aa3242/.cache/huggingface:/root/.cache/huggingface:ro \
  --env HF_HUB_OFFLINE=1 --env TRANSFORMERS_OFFLINE=1 \
  --entrypoint /opt/python/bin/vllm "$image" serve "$model" \
  --host 0.0.0.0 --port "$port" --served-model-name "$model" \
  --dtype bfloat16 --enforce-eager --max-model-len 65536 --data-parallel-size 8 \
  --max-num-seqs 256 --gpu-memory-utilization 0.90 --enable-prefix-caching \
  --no-async-scheduling --attention-backend TRITON_ATTN \
  --enable-expert-parallel --all2all-backend naive \
  --reasoning-parser openai_gptoss --tool-call-parser openai \
  --enable-auto-tool-choice --trust-remote-code > "$run/container-id.txt"

sudo -n docker logs --follow "$container" > "$run/vllm.log" 2>&1 &
logger_pid=$!
ready=0
for _ in $(seq 1 360); do
  if curl --fail --silent "http://127.0.0.1:${port}/v1/models" > "$run/models.pending.json"; then
    mv "$run/models.pending.json" "$run/models.json"; ready=1; break
  fi
  if ! sudo -n docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null | grep -qx true; then
    sudo -n docker logs "$container" >&2 || true; exit 1
  fi
  sleep 5
done
if [[ "$ready" != 1 ]]; then echo "vLLM startup timed out" >&2; exit 1; fi
date -Is > "$run/server-ready.txt"

export OPENAI_COMPAT_BASE_URL="http://127.0.0.1:${port}/v1"
export OPENAI_COMPAT_MODEL="$model"
export CODEX_OSS_BASE_URL="$OPENAI_COMPAT_BASE_URL"
cd "$repo"
no_tools_complete=0
for resume in $(seq 1 4); do
  set +e
  model_evals/gemini/.venv/bin/python -u model_evals/gpt_oss/run_corrected_no_tools.py \
    >> "$run/suite.log" 2>&1
  set -e
  if model_evals/gemini/.venv/bin/python - <<'PY'
import json
from pathlib import Path

paths = [
    Path("model_evals/gpt_oss/runs/gpt-oss-120b-high-no-tools-corrected-20260914/phybench/summary.json"),
    Path("model_evals/gpt_oss/runs/gpt-oss-120b-high-no-tools-corrected-20260914/prism/summary.json"),
    Path("model_evals/gpt_oss/runs/gpt-oss-120b-high-no-tools-corrected-20260914/ugphysics/summary.json"),
    Path("benchmarks/hle/artifacts/gpt-oss-120b-high-no-tools-corrected-20260914/hle-corrected.summary.json"),
    Path("analysis/CMT-Benchmark/artifacts/gpt-oss-120b-high-no-tools-corrected-20260914/cmt-corrected.summary.json"),
    Path("analysis/CritPt/artifacts/gpt-oss-120b-high-no-tools-corrected-20260914/critpt-corrected.summary.json"),
]
raise SystemExit(0 if all(path.exists() and json.loads(path.read_text()).get("complete")
                          for path in paths) else 1)
PY
  then
    no_tools_complete=1
    break
  fi
done
if [[ "$no_tools_complete" != 1 ]]; then
  echo "No-tools suite remains incomplete after resume attempts" >&2
  exit 2
fi
date -Is > "$run/no-tools-complete.txt"

if [[ -x "$repo/model_evals/gpt_oss/jobs/run_tools.sh" ]]; then
  mkdir -p "$tools_run"
  model_evals/gemini/.venv/bin/python -u model_evals/gpt_oss/responses_proxy.py \
    --listen-port 8001 --upstream "http://127.0.0.1:${port}" \
    --log "$tools_run/proxy-requests.jsonl" \
    >> "$tools_run/proxy.log" 2>&1 &
  proxy_pid=$!
  tools_code=1
  for tools_attempt in $(seq 1 10); do
    set +e
    "$repo/model_evals/gpt_oss/jobs/run_tools.sh" "$port" >> "$run/tools-suite.log" 2>&1
    tools_code=$?
    set -e
    printf '%s\n' "$tools_code" > "$run/tools-exit-code.txt"
    [[ "$tools_code" == 0 ]] && break
    sleep 60
  done
fi
date -Is > "$run/all-complete.txt"
kill "$logger_pid" >/dev/null 2>&1 || true
