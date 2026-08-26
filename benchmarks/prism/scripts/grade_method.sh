#!/usr/bin/env bash
set -eo pipefail

declare -a MODELS  # will fill from CLI or default later

# Optional central config
[[ -f scripts/run.conf ]] && source scripts/run.conf

# Defaults (can be overridden by env or CLI)
BASE_DIR="${BASE_DIR:-debug_with_verify}"
NAME="${NAME:-ours_examples}"
METHOD="${METHOD:-dag}"

# # Usage: eval_method.sh <method> [--base DIR] [--name NAME] [--models m1 [m2 ...]] [-- ...extra eval flags...]
# if [[ $# -lt 1 ]]; then
#   echo "Usage: $0 <method> [--base DIR] [--name NAME] [--models m1 [m2 ...]] [-- ...extra eval flags...]"
#   exit 1
# fi

METHOD="${1:-$METHOD}"  # If $1 is unset/empty, keep original METHOD
[[ $# -gt 0 ]] && shift  # Only shift if an arg was actually passed

# Parse our own flags; forward the rest (after -- or unknowns)
EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --base|-b)
      BASE_DIR="${2:?missing DIR}"; shift 2;;
    --log_path)
      log_path="${2:?missing LOG}"; shift 2;;
    --name|-n)
      NAME="${2:?missing NAME}"; shift 2;;
    --models)
      shift  # eat the flag
      MODELS=()
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
    *)   # unknown to this script; forward
      EXTRA_ARGS+=("$1"); shift;;
  esac
done

# Default models if none provided anywhere
if ((${#MODELS[@]} == 0)); then
  MODELS=(deepseek-v3)
fi

problems_file="${BASE_DIR}/${NAME}_${METHOD}.json"
results_dir="${BASE_DIR}/results_${NAME}_${METHOD}"
if [ -z "${log_path+x}" ]; then
    log_path="${results_dir}/output.log"
fi
mkdir -p "$results_dir"

source scripts/set_api_key.sh

python -u -m eval.grade \
  --models "${MODELS[@]}" \
  --problems_file "$problems_file" \
  --slice 0 10 \
  --threshold 0.8 \
  --results_dir "$results_dir" \
  --log_path "$log_path" \
  --method "$METHOD" \
  --json_logs \
  "${EXTRA_ARGS[@]}"


