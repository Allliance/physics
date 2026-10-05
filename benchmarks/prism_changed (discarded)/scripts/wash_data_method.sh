#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   wash_data_run.sh <method> [flags for data.wash_data...]
METHOD="${1:?Usage: $0 <method> [flags]}"
shift || true

source scripts/set_api_key.sh
python -u -m data.wash_data --method "$METHOD" "$@"
