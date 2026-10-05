#!/usr/bin/env bash
#SBATCH --job-name=physics-openrouter-evals
#SBATCH --partition=amd-mi355x
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=128
#SBATCH --mem=256G
#SBATCH --time=24:00:00
#SBATCH --output=/shared/data/home/aa3242/physics/model_evals/open_models/openrouter-sequence-%j.log

set -euo pipefail

# No --gres/--gpus request: this job uses CPU/network only. All evaluated-model
# inference is served by OpenRouter.
exec /shared/data/home/aa3242/physics/model_evals/open_models/jobs/run_openrouter_sequence.sh
