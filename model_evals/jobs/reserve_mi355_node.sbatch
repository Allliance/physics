#!/usr/bin/env bash
#SBATCH --job-name=mi355-reserve
#SBATCH --partition=amd-mi355x
#SBATCH --nodelist=mi355-gpu-35
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:8
#SBATCH --cpus-per-task=256
#SBATCH --mem=2900000M
#SBATCH --time=24:00:00
#SBATCH --output=/shared/data/home/aa3242/physics/model_evals/slurm/mi355-reserve-%j.out
#SBATCH --error=/shared/data/home/aa3242/physics/model_evals/slurm/mi355-reserve-%j.err

set -euo pipefail

echo "job_id=$SLURM_JOB_ID"
echo "node=$(hostname)"
echo "started_at=$(date -Is)"
echo "expires_at=${SLURM_JOB_END_TIME:-managed-by-slurm-time-limit}"
rocm-smi --showproductname

sleep infinity
