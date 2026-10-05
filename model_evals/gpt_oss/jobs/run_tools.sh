#!/usr/bin/env bash
set -uo pipefail

port=${CODEX_OSS_PROXY_PORT:-8001}
repo=/shared/data/home/aa3242/physics
python="$repo/model_evals/gemini/.venv/bin/python"
tag=gpt-oss-120b-high-tools-corrected-20260914
run="$repo/model_evals/gpt_oss/runs/$tag"
source_data="$repo/model_evals/gemini/runs/gemini31-20260908/repeated"
workers=${GPT_OSS_TOOL_WORKERS:-80}
mkdir -p "$run/logs"
export OPENAI_COMPAT_BASE_URL="http://127.0.0.1:${port}/v1"
export OPENAI_COMPAT_MODEL=openai/gpt-oss-120b
export CODEX_OSS_BASE_URL="$OPENAI_COMPAT_BASE_URL"
export PYTHONPATH="$repo:$repo/utils${PYTHONPATH:+:$PYTHONPATH}"
cd "$repo"

"$python" -u model_evals/gpt_oss/smoke_codex_tools.py > "$run/codex-tool-smoke.json" 2> "$run/codex-tool-smoke.err"
smoke_code=$?
if [[ "$smoke_code" -ne 0 ]]; then
  echo "Codex tool smoke failed with exit code $smoke_code" >&2
  exit "$smoke_code"
fi

GPT_OSS_TOOL_WORKERS="$workers" "$python" -u model_evals/gpt_oss/run_corrected_tools.py
date -Is > "$run/complete.txt"
