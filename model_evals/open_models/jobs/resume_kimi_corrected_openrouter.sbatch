#!/usr/bin/env bash
#SBATCH --job-name=kimi-corrected-openrouter
#SBATCH --partition=amd-mi355x
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH --time=06:00:00
#SBATCH --output=/shared/data/home/aa3242/physics/model_evals/kimi/runs/kimi-k3-max-no-tools-20260917/hle-corrected/openrouter-resume-%j.log

set -euo pipefail

# Deliberately no --gres/--gpus request: inference is remote on OpenRouter.
exec /shared/data/home/aa3242/physics/model_evals/open_models/jobs/resume_kimi_corrected_openrouter.sh
