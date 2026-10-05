#!/usr/bin/env bash
set -eo pipefail

declare -a MODELS  # will fill from run.conf or CLI

# Optional central config
[[ -f scripts/run.conf ]] && source scripts/run.conf

# ---- Normalize MODELS from run.conf to an array (handles string vs array) ----
# If MODELS is unset, leave as empty array.
if [[ -n "${MODELS+x}" && ! "$(declare -p MODELS 2>/dev/null)" =~ "declare -a" ]]; then
  # MODELS exists but is not an array (likely a space-separated string) -> split to array
  read -r -a MODELS <<< "${MODELS}"
fi

# Defaults (can be overridden by env or CLI)
BASE_DIR="${BASE_DIR:-main}"
NAME="${NAME:-example}"
METHOD="${METHOD:-dag}"

METHOD="${1:-$METHOD}"  # If $1 is unset/empty, keep original METHOD
[[ $# -gt 0 ]] && shift  # Only shift if an arg was actually passed

# Parse our own flags; forward the rest (after -- or unknowns)
EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --base|-b)
      BASE_DIR="${2:?missing DIR}"; shift 2;;
    --name|-n)
      NAME="${2:?missing NAME}"; shift 2;;
    --models)
      shift  # consume the flag itself
      MODELS=()  # <-- IMPORTANT: override anything from run.conf
      # Collect models until next flag (starts with '-') or end
      while [[ $# -gt 0 && "$1" != --* ]]; do
        MODELS+=("$1")
        shift
      done
      ;;
    --)  # forward the rest verbatim
      shift
      EXTRA_ARGS+=("$@")
      break
      ;;
    *)
      # unknown to this script; forward
      EXTRA_ARGS+=("$1"); shift;;
  esac
done

# Default models if none provided anywhere
if ((${#MODELS[@]} == 0)); then
  MODELS=(deepseek-v3)
fi

problems_file="${BASE_DIR}/${NAME}_${METHOD}.json"
results_dir="${BASE_DIR}/results_${NAME}_${METHOD}"
log_path="${results_dir}/output.log"
mkdir -p "$results_dir"

source scripts/set_api_key.sh

# Debug print (optional)
echo "[eval_method] METHOD=${METHOD}"
echo "[eval_method] MODELS: ${MODELS[*]}"
echo "[eval_method] EXTRA_ARGS: ${EXTRA_ARGS[*]}"

python -u -m eval.eval \
  --models "${MODELS[@]}" \
  --problems_file "$problems_file" \
  --threshold 0.8 \
  --results_dir "$results_dir" \
  --log_path "$log_path" \
  --method "$METHOD" \
  --json_logs \
  "${EXTRA_ARGS[@]}"
