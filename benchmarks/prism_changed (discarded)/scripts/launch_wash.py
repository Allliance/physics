#!/usr/bin/env python3
import argparse
import os
import json
import subprocess
import sys
from pathlib import Path

DEFAULTS = {
    "BASE_DIR": "example",
    "MODEL": "gpt-5-medium",
    "WORKERS": 4,
    "LOG_LEVEL": "DEBUG",
    "START": -1,
    "END": -1,
    "MAX_ATTEMPTS": 5,
    "LOG_DIR": "logs",
}


def load_config(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def getenv_or(defaults: dict) -> dict:
    """Read environment overrides (string envs only)."""
    out = {}
    for key in defaults:
        if key in os.environ:
            out[key] = os.environ[key]
    # Special case: METHODS env is space-separated
    if "METHODS" in os.environ:
        out["METHODS"] = os.environ["METHODS"].split()
    return out


def submit(args: list[str]) -> str:
    """Run sbatch and return jobid string."""
    proc = subprocess.run(["sbatch", "--parsable"] + args,
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,
                          text=True)
    if proc.returncode != 0:
        print("sbatch failed:", proc.stderr, file=sys.stderr)
        sys.exit(proc.returncode)
    return proc.stdout.strip()


def main():
    parser = argparse.ArgumentParser(
        description="Launch wash_data jobs with sbatch")
    parser.add_argument("--config", default="scripts/config.json", help="Optional JSON config file")
    parser.add_argument("--base", dest="BASE_DIR")
    parser.add_argument("--methods", nargs="+", help="List of methods")
    parser.add_argument("--names", dest="NAMES", nargs="+", help="Experiment names")
    parser.add_argument("--model")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--log-level")
    parser.add_argument("--start", type=int)
    parser.add_argument("--end", type=int)
    parser.add_argument("--max-attempts", type=int)
    parser.add_argument("--log-dir")
    parser.add_argument("positional", nargs="*", help="extra passthrough flags")

    args, extra = parser.parse_known_args()

    # Load config
    config = load_config(args.config) if args.config else {}

    # Merge precedence: CLI > env > config > defaults
    merged = dict(DEFAULTS)
    merged.update(config)
    merged.update(getenv_or(DEFAULTS))
    cli_dict = {k: v for k, v in vars(args).items() if v is not None}
    merged.update(cli_dict)

    base_dir = merged["BASE_DIR"]
    model = merged["MODEL"]
    workers = int(merged["WORKERS"])
    log_level = merged["LOG_LEVEL"]
    start = int(merged["START"])
    end = int(merged["END"])
    max_attempts = int(merged["MAX_ATTEMPTS"])
    log_dir = merged["LOG_DIR"]

    Path(log_dir).mkdir(parents=True, exist_ok=True)

    methods = merged.get("methods") or merged.get("METHODS")
    if not methods:
        print("Error: no methods specified", file=sys.stderr)
        sys.exit(1)

    names = merged.get("NAMES") or ["default"]    
    last_jobid=None

    for name in names:
        stage2_out = f"{base_dir}/{name}_stage2"
        Path(f"{base_dir}/{name}").mkdir(parents=True, exist_ok=True)
        raw_file = f"{base_dir}/{name}.json"

        if len(methods) == 1:
            m = methods[0]
            submit([
                f"--job-name=wash_{name}_{m}",
                f"--output={log_dir}/wash_{name}_{m}_%j.out",
                f"--error={log_dir}/wash_{name}_{m}_%j.err",
                f"--cpus-per-task={workers}",
                "scripts/wash_data_sbatch.sh", m,
                "--raw", raw_file,
                "--out", f"{base_dir}/{name}_{m}",
                "--model", model,
                "--start", str(start), "--end", str(end),
                "--max-attempts", str(max_attempts),
                "--num-stages", "1", "2", "3",
                "--workers", str(workers),
                "--log-file", f"{log_dir}/wash_{name}_{m}.log",
                "--log-level", log_level,
            ] + extra)
        else:
            first = methods[0]
            args = [
                f"--job-name=wash_{name}_stage2",
                f"--output={log_dir}/wash_{name}_stage2_%j.out",
                f"--error={log_dir}/wash_{name}_stage2_%j.err",
                f"--cpus-per-task={workers}",
                "scripts/wash_data_sbatch.sh", first,
                "--raw", raw_file,
                "--out", stage2_out,
                "--model", model,
                "--start", str(start), "--end", str(end),
                "--max-attempts", str(max_attempts),
                "--num-stages", "1", "2",
                "--workers", str(workers),
                "--log-file", f"{log_dir}/wash_{name}_stage2.log",
                "--log-level", log_level,
            ] + extra
            # if last_jobid is not None:
            #     args = [f"--dependency=afterok:{last_jobid}"] + args
            stage2_jobid = submit(args)

            print(f"Submitted stage-2 precompute job for {name}: {stage2_jobid}")
            if last_jobid is not None:
                print(f"It should wait until job id {last_jobid} finishes")

            for m in methods:
                last_jobid = submit([
                    f"--dependency=afterok:{stage2_jobid}",
                    f"--job-name=wash_{name}_{m}",
                    f"--output={log_dir}/wash_{name}_{m}_%j.out",
                    f"--error={log_dir}/wash_{name}_{m}_%j.err",
                    f"--cpus-per-task={workers}",
                    "scripts/wash_data_sbatch.sh", m,
                    "--raw", f"{stage2_out}.json",
                    "--out", f"{base_dir}/{name}_{m}",
                    "--model", model,
                    "--start", str(start), "--end", str(end),
                    "--max-attempts", str(max_attempts),
                    "--num-stages", "3",
                    "--workers", str(workers),
                    "--log-file", f"{log_dir}/wash_{name}_{m}.log",
                    "--log-level", log_level,
                ] + extra)


if __name__ == "__main__":
    main()
