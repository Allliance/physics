#!/usr/bin/env bash
#SBATCH --time=24:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1          # will be overridden by --cpus-per-task=... at submit time
#SBATCH --mem-per-cpu=10G
#SBATCH --partition=jamesz

set -euo pipefail

# If your cluster doesn't have Lmod, the 'module' line will just be ignored.
module load python/3.12.1 || true
source /home/users/wanjiazh/ai4s_venv/bin/activate

# Pass everything through to the runner. First arg must be the method.
bash scripts/wash_data_method.sh "$@"
