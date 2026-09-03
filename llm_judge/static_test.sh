#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(dirname "$script_dir")
cd "$repo_root"

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--live" ) ]]; then
    echo "usage: $0 [--live]" >&2
    exit 2
fi
live_mode=${1:-}

bash -n llm_judge/start_judge_server.sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
    -s llm_judge/tests \
    -p 'test_*.py'

PYTHONDONTWRITEBYTECODE=1 python3 -m llm_judge.eval \
    --backend openai \
    --model static-test \
    --sample-size 20 \
    --sample-seed 20260903 \
    --dry-run \
    | python3 -c '
import json
import sys

EXPECTED_SELECTION_HASH = "7eaa8b4c964e3993cd9a0263dd04106e0e035498fc6da2216f49febbda28b0fa"
preview = json.load(sys.stdin)
assert preview["num_selected"] == 20, preview["num_selected"]
assert preview["selection"]["method"] == "random", preview["selection"]
assert preview["selection"]["sample_seed"] == 20260903, preview["selection"]
assert preview["selection"]["selected_ids_sha256"] == EXPECTED_SELECTION_HASH, preview["selection"]
'

echo "LLM judge network-free static tests passed."

if [[ "$live_mode" != "--live" ]]; then
    exit 0
fi

: "${OPENAI_BASE_URL:?source the judge server endpoint.env before using --live}"
live_model=${OPENAI_MODEL:-Qwen/Qwen3.5-27B}
live_api_key=${OPENAI_API_KEY:-EMPTY}
live_output="$repo_root/llm_judge/judgements/static-live-qwen35-27b.jsonl"
live_summary="$repo_root/llm_judge/judgements/static-live-qwen35-27b.summary.json"

evaluation_status=0
PYTHONDONTWRITEBYTECODE=1 python3 -m llm_judge.eval \
    --backend openai \
    --model "$live_model" \
    --base-url "$OPENAI_BASE_URL" \
    --api-key "$live_api_key" \
    --max-workers 100 \
    --timeout 600 \
    --max-tokens 8192 \
    --temperature 0.6 \
    --top-p 0.95 \
    --extra-body '{"chat_template_kwargs":{"enable_thinking":true},"thinking_token_budget":4096,"top_k":20,"min_p":0.0}' \
    --sample-size 100 \
    --sample-seed 42 \
    --output "$live_output" \
    --overwrite \
    >/dev/null || evaluation_status=$?

if [[ "$evaluation_status" -gt 1 ]]; then
    echo "live evaluation failed with status $evaluation_status" >&2
    exit "$evaluation_status"
fi

python3 - "$live_summary" <<'PY'
import json
import sys
from pathlib import Path

SOFT_ACCURACY_THRESHOLD = 0.95
summary = json.loads(Path(sys.argv[1]).read_text())
confusion = summary["metrics"]["confusion_matrix"]
correct = (
    confusion["true_solved_predicted_solved"]
    + confusion["true_unsolved_predicted_unsolved"]
)
selected = summary["num_selected"]
soft_accuracy = correct / selected
print(
    f"Soft live judge test: {correct}/{selected} correct "
    f"({soft_accuracy:.2%}), {summary['num_errors']} errors."
)
if soft_accuracy < SOFT_ACCURACY_THRESHOLD:
    raise SystemExit(
        f"soft live accuracy {soft_accuracy:.2%} is below "
        f"{SOFT_ACCURACY_THRESHOLD:.0%}"
    )
PY
