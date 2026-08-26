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


def run_and_log(cmd: list[str], log_file: Path) -> subprocess.CompletedProcess:
    """Run command and log output to file"""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Running: {' '.join(cmd)}")
    print(f"Logging to: {log_file}")
    
    with log_file.open("w") as f:
        f.write(f"Command: {' '.join(cmd)}\n")
        f.write("=" * 80 + "\n\n")
        f.flush()
        
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False
        )
        
        f.write(proc.stdout)
        
    if proc.returncode != 0:
        print(f"ERROR: Command failed with return code {proc.returncode}")
        print(f"Check log: {log_file}")
        sys.exit(proc.returncode)
    
    return proc


def main():
    parser = argparse.ArgumentParser(
        description="Launch wash_data jobs directly (no sbatch)")
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
    
    print("=" * 80)
    print("DIRECT WASH_DATA LAUNCHER (no sbatch)")
    print("=" * 80)
    print(f"Methods: {', '.join(methods)}")
    print(f"Names: {', '.join(names)}")
    print(f"Model: {model}")
    print(f"Workers: {workers}")
    print(f"Base dir: {base_dir}")
    print("=" * 80)

    for name in names:
        print(f"\n{'=' * 80}")
        print(f"Processing NAME: {name}")
        print(f"{'=' * 80}")
        
        stage2_out = f"{base_dir}/{name}_stage2"
        Path(f"{base_dir}/{name}").mkdir(parents=True, exist_ok=True)
        raw_file = f"{base_dir}/{name}.json"

        if len(methods) == 1:
            # Single method: run all stages in one go
            m = methods[0]
            print(f"\n[{name}] Running single method {m} (stages 1, 2, 3)")
            
            log_file = Path(log_dir) / f"wash_{name}_{m}.out"
            
            cmd = [
                "bash", "scripts/wash_data_method.sh", m,
                "--raw", raw_file,
                "--out", f"{base_dir}/{name}_{m}",
                "--model", model,
                "--start", str(start), "--end", str(end),
                "--max-attempts", str(max_attempts),
                "--num-stages", "1", "2", "3",
                "--workers", str(workers),
                "--log-file", f"{log_dir}/wash_{name}_{m}.log",
                "--log-level", log_level,
            ] + extra
            
            run_and_log(cmd, log_file)
            print(f"[{name}] Method {m} completed successfully")
            
        else:
            # Multiple methods: run stage 1-2 precompute, then stage 3 for each method
            first = methods[0]
            print(f"\n[{name}] Running stage 1-2 precompute with method {first}")
            
            stage2_log = Path(log_dir) / f"wash_{name}_stage2.out"
            
            stage2_cmd = [
                "bash", "scripts/wash_data_method.sh", first,
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
            
            run_and_log(stage2_cmd, stage2_log)
            print(f"[{name}] Stage 1-2 precompute completed successfully")

            # Now run stage 3 for each method
            for m in methods:
                print(f"\n[{name}] Running stage 3 for method {m}")
                
                log_file = Path(log_dir) / f"wash_{name}_{m}.out"
                
                cmd = [
                    "bash", "scripts/wash_data_method.sh", m,
                    "--raw", f"{stage2_out}.json",
                    "--out", f"{base_dir}/{name}_{m}",
                    "--model", model,
                    "--start", str(start), "--end", str(end),
                    "--max-attempts", str(max_attempts),
                    "--num-stages", "3",
                    "--workers", str(workers),
                    "--log-file", f"{log_dir}/wash_{name}_{m}.log",
                    "--log-level", log_level,
                ] + extra
                
                run_and_log(cmd, log_file)
                print(f"[{name}] Method {m} (stage 3) completed successfully")

    print(f"\n{'=' * 80}")
    print("ALL TASKS COMPLETED SUCCESSFULLY")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    main()