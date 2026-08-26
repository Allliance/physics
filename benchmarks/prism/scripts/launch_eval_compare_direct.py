#!/usr/bin/env python3
import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

DEFAULTS: Dict[str, Any] = {
    "BASE_DIR": "debug",
    "NAMES": [],
    "METHODS": [],
    "MODEL": "gpt-4.1",
    "MODE": "text",
    "WORKERS": 4,
    "LOG_LEVEL": "DEBUG",
    "START": -1,
    "END": -1,
    "MAX_ATTEMPTS": 5,
    "MODELS": ["deepseek-v3"],
    "PARTITION": "jamesz",
    "GEN_METHOD": None,
    "LOG_DIR": "logs",
}

# ---------- helpers ----------
def split_cli_args(argv: List[str]) -> Tuple[List[str], List[str]]:
    if "--" in argv:
        i = argv.index("--")
        return argv[:i], argv[i+1:]
    return argv, []

def load_config(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.is_file():
        return {}
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def env_overrides() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    scalar_keys = [
        "BASE_DIR","MODEL","MODE","LOG_LEVEL","START","END",
        "MAX_ATTEMPTS","PARTITION","GEN_METHOD","LOG_DIR","NAME"
    ]
    for k in scalar_keys:
        if k in os.environ:
            out[k] = os.environ[k]
    # arrays as space-separated envs
    if "NAMES" in os.environ:
        out["NAMES"] = os.environ["NAMES"].split()
    if "METHODS" in os.environ:
        out["METHODS"] = os.environ["METHODS"].split()
    if "MODELS" in os.environ:
        out["MODELS"] = os.environ["MODELS"].split()
    if "WORKERS" in os.environ:
        try:
            out["WORKERS"] = int(os.environ["WORKERS"])
        except ValueError:
            pass
    return out

def run_and_log(cmd: List[str], log_file: Path) -> subprocess.CompletedProcess:
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

# ---------- arg parsing & merge ----------
def parse_args() -> Tuple[argparse.Namespace, List[str]]:
    pre_argv, extra = split_cli_args(sys.argv[1:])
    p = argparse.ArgumentParser(description="Direct parallel generator+grader launcher (no sbatch).")
    p.add_argument("--config", default="scripts/config.json", help="Path to JSON config (default: scripts/config.json)")
    p.add_argument("--base", dest="BASE_DIR")
    p.add_argument("--names", nargs="+")
    p.add_argument("--name", dest="NAME")
    p.add_argument("--methods", nargs="+")
    p.add_argument("--gen-method", "--generator", dest="GEN_METHOD")
    p.add_argument("--models", nargs="+", dest="MODELS")
    p.add_argument("--mode", dest="MODE", choices=["text", "multimodal"])
    p.add_argument("--log-level", dest="LOG_LEVEL")
    p.add_argument("--log-dir", dest="LOG_DIR")
    p.add_argument("--partition", dest="PARTITION")
    p.add_argument("--workers", dest="WORKERS", type=int)
    p.add_argument("--slice", dest="SLICE", type=int, nargs=2, metavar=("START","END"))
    p.add_argument("--skip-gen", default=False, action="store_true")
    p.add_argument("positional_methods", nargs="*")
    args = p.parse_args(pre_argv)
    return args, extra

def merge_config(args: argparse.Namespace) -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    cfg.update(load_config(getattr(args, "config", None)))
    cfg.update(env_overrides())

    # CLI overrides
    for k, v in vars(args).items():
        if k == "config":
            continue
        if v not in (None, [], ""):
            cfg[k] = v

    # METHODS
    methods = cfg.get("methods") or cfg.get("METHODS") or []
    if not methods and cfg.get("positional_methods"):
        methods = cfg["positional_methods"]
    cfg["METHODS"] = methods

    # NAMES
    names = cfg.get("names") or cfg.get("NAMES") or []
    if not names:
        names = [cfg.get("NAME") or "ours_examples"]
    cfg["NAMES"] = names

    # GEN_METHOD
    if not cfg.get("GEN_METHOD"):
        if methods:
            cfg["GEN_METHOD"] = methods[0]

    # Normalize numeric
    for k in ["WORKERS","START","END","MAX_ATTEMPTS"]:
        try:
            cfg[k] = int(cfg[k])
        except Exception:
            pass

    # If --slice provided, it wins and sets START/END
    if "SLICE" in cfg and cfg["SLICE"]:
        cfg["START"], cfg["END"] = cfg["SLICE"][0], cfg["SLICE"][1]

    return cfg

# ---------- main ----------
def main():
    args, extra = parse_args()
    cfg = merge_config(args)

    base_dir: str = cfg["BASE_DIR"]
    names: List[str] = cfg["NAMES"]
    methods: List[str] = cfg["METHODS"]
    gen_method: str = cfg["GEN_METHOD"]
    models: List[str] = cfg["MODELS"]
    mode: str = cfg["MODE"]
    log_level: str = cfg["LOG_LEVEL"]
    start_i: int = cfg["START"]
    end_i: int = cfg["END"]
    log_dir = Path(cfg["LOG_DIR"])
    log_dir.mkdir(parents=True, exist_ok=True)

    if not methods:
        print("Error: no methods provided (use --methods or config).", file=sys.stderr)
        sys.exit(1)
    if not gen_method:
        print("Error: GEN_METHOD could not be determined.", file=sys.stderr)
        sys.exit(1)

    print("=" * 80)
    print("DIRECT LAUNCHER (no sbatch)")
    print("=" * 80)
    print("Using methods:", " ".join(methods))
    print("Generator method:", gen_method)
    print("Models:", " ".join(models))
    print("Mode:", mode)
    print(f"Config: base_dir={base_dir}, names={names}")
    print(f"Slice: [{start_i}, {end_i}]")
    print("=" * 80)

    for name in names:
        print(f"\n{'=' * 80}")
        print(f"Processing NAME: {name}")
        print(f"{'=' * 80}")
        
        # -------- 1) generator job --------
        if not args.skip_gen:
            print(f"\n[{name}] Running generator: {gen_method}")
            gen_log = log_dir / f"gen_{name}_{gen_method}.out"
            
            gen_cmd = [
                "bash", "scripts/eval_method.sh", gen_method,
                "--base", base_dir,
                "--name", name,
                "--models", *models,
                "--log_level", log_level,
                "--mode", mode,
                "--slice", str(start_i), str(end_i),
            ]
            if extra:
                gen_cmd.extend(["--"] + extra)
            
            run_and_log(gen_cmd, gen_log)
            print(f"[{name}] Generator completed successfully")

            # -------- 2) copy jobs for non-gen methods --------
            gen_results_dir = Path(base_dir) / f"results_{name}_{gen_method}" / mode

            for m in methods:
                if m == gen_method:
                    continue
                
                print(f"\n[{name}] Copying results for method: {m}")
                copy_log = log_dir / f"copy_{name}_{m}.out"
                
                # Perform copy operations
                for model in models:
                    src = gen_results_dir / model / "responses" / f"{model}_final_responses.json"
                    dest_dir = Path(base_dir) / f"results_{name}_{m}" / mode / model / "responses"
                    
                    if src.exists():
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        import shutil
                        shutil.copy2(src, dest_dir / f"{model}_final_responses.json")
                        print(f"  Copied: {src} -> {dest_dir}")
                    else:
                        print(f"  WARNING: Source not found: {src}")
                
                # Log the copy operation
                with copy_log.open("w") as f:
                    f.write(f"Copy operation for {name}/{m} completed\n")
                
                print(f"[{name}] Copy for {m} completed")

        # -------- 3) grading jobs --------
        for m in methods:
            print(f"\n[{name}] Running grading for method: {m}")
            grade_log = log_dir / f"grade_{name}_{m}.out"
            
            grade_cmd = [
                "bash", "scripts/grade_method.sh", m,
                "--base", base_dir,
                "--name", name,
                "--models", *models,
                "--log_level", log_level,
                "--slice", str(start_i), str(end_i),
                "--mode", mode,
            ]
            if extra:
                grade_cmd.extend(["--"] + extra)
            
            run_and_log(grade_cmd, grade_log)
            print(f"[{name}] Grading for {m} completed successfully")

    print(f"\n{'=' * 80}")
    print("ALL TASKS COMPLETED SUCCESSFULLY")
    print(f"{'=' * 80}")

if __name__ == "__main__":
    main()