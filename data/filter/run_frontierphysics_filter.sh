#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

python3 "${SCRIPT_DIR}/filter_dataset.py" \
  --input-dir "${REPO_ROOT}/original_datasets/prepared/FrontierPhysics" \
  --output-dir "${REPO_ROOT}/filtered_datasets/prepared/FrontierPhysics" \
  "$@"
