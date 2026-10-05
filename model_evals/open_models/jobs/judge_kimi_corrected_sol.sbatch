#!/usr/bin/env bash
#SBATCH --job-name=kimi-corrected-sol-judge
#SBATCH --partition=amd-mi355x
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=128
#SBATCH --mem=128G
#SBATCH --time=06:00:00
#SBATCH --output=/shared/data/home/aa3242/physics/model_evals/kimi/runs/kimi-k3-max-no-tools-20260917/hle-corrected/sol-judge-%j.log

set -euo pipefail

repo=/shared/data/home/aa3242/physics
cd "$repo"

# No GPU is requested. Twenty incomplete benchmark-attempt jobs run in
# parallel, each with ten Sol judge workers (up to 200 concurrent judges).
exec "$repo/model_evals/gemini/.venv/bin/python" -u \
    "$repo/model_evals/open_models/run_corrected_hle.py" \
    --model kimi-k3 \
    --benchmarks phybench prism ugphysics hle cmt critpt \
    --base-url https://openrouter.ai/api/v1 \
    --served-model moonshotai/kimi-k3 \
    --manifest-base-url http://127.0.0.1:8000/v1 \
    --manifest-model moonshotai/Kimi-K3 \
    --generation-workers 1 \
    --judge-workers 10 \
    --parallel 24 \
    --retries 8 \
    --transport-timeout 10800 \
    --stage judge
