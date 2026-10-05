#!/usr/bin/env bash
set -euo pipefail

job_id=${1:?usage: run_when_ready.sh SLURM_JOB_ID}
repo=/shared/data/home/aa3242/physics
server="$repo/model_evals/kimi/runs/server-${job_id}"
suite="$repo/model_evals/kimi/runs/kimi-k3-max-no-tools-20260917"
mkdir -p "$suite"

for _ in $(seq 1 4320); do
    [[ -f "$server/endpoint.json" ]] && break
    if ! squeue -h -j "$job_id" | grep -q .; then
        echo "Server job $job_id ended before becoming ready" >&2
        exit 1
    fi
    sleep 10
done
[[ -f "$server/endpoint.json" ]] || { echo "Timed out waiting for Kimi server" >&2; exit 1; }

mapfile -t endpoint < <(python3 - "$server/endpoint.json" <<'PY'
import json, sys
value = json.load(open(sys.argv[1]))
print(value["base_url"])
print(value["model"])
PY
)
export OPENAI_COMPAT_BASE_URL=${endpoint[0]}
export OPENAI_COMPAT_MODEL=${endpoint[1]}

cd "$repo"
model_evals/gemini/.venv/bin/python - <<'PY' >"$suite/smoke.json"
import json
from utils.openai_compatible import generate

result = generate(
    "Return the integer obtained by adding 2 and 2.",
    system_prompt="Solve the problem and return only the requested JSON object.",
    reasoning_effort="max",
    max_output_tokens=8192,
    timeout=1800,
    temperature=1.0,
    top_p=0.95,
    output_schema={
        "type": "object",
        "properties": {"answer": {"type": "integer"}},
        "required": ["answer"],
        "additionalProperties": False,
    },
)
if json.loads(result["response"])["answer"] != 4:
    raise ValueError(f"Kimi smoke answer failed: {result}")
print(json.dumps(result, indent=2))
PY
date -Is >"$suite/smoke-complete.txt"

model_evals/gemini/.venv/bin/python -u model_evals/kimi/run_suite.py \
    --workers 8 --judge-workers 16 --parallel 17 --retries 3 \
    >>"$suite/supervisor.log" 2>&1
date -Is >"$suite/complete.txt"
