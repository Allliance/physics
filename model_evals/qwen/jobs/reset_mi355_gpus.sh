#!/usr/bin/env bash

set -euo pipefail

echo "job_id=$SLURM_JOB_ID node=$(hostname) started_at=$(date -Is)"
sudo -n docker ps -a --format '{{.Names}}' | while IFS= read -r container; do
    case "$container" in
        qwen-qwen3-*-vllm-*|qwen35-*-vllm-*)
            sudo -n docker rm -f "$container" >/dev/null
            ;;
    esac
done
for device in 0 1 2 3 4 5 6 7; do
    sudo -n rocm-smi --device "$device" --gpureset
done
rocm-smi --showmeminfo vram
echo "reset_finished_at=$(date -Is)"
