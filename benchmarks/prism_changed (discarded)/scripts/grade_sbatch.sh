#!/usr/bin/env bash
#SBATCH --time=10:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem-per-cpu=10G
#SBATCH --partition=jamesz
#SBATCH --job-name="eval"
#SBATCH --output="logs/grade.out"
#SBATCH --error="logs/grade.err"

set -euo pipefail

module load python/3.12.1 || true
source /home/users/wanjiazh/ai4s_venv/bin/activate

# Pass everything through (method first, then flags)
echo "grade with config: $@"
bash scripts/grade_method.sh "$@"
