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

def run(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)

def submit(args: List[str], parsable: bool = True) -> str:
    cmd = ["sbatch"]
    if parsable:
        cmd.append("--parsable")
    cmd += args
    proc = run(cmd)
    if proc.returncode != 0:
        print("sbatch failed:\n", proc.stderr, file=sys.stderr)
        sys.exit(proc.returncode)
    return proc.stdout.strip()

# ---------- arg parsing & merge ----------
def parse_args() -> Tuple[argparse.Namespace, List[str]]:
    pre_argv, extra = split_cli_args(sys.argv[1:])
    p = argparse.ArgumentParser(description="Parallel generator+grader launcher with sbatch dependencies.")
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
    # Optional CLI override matching your downstream parser: --slice START END
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
    partition: str = cfg["PARTITION"]
    workers: int = cfg["WORKERS"]
    start_i: int = cfg["START"]          # <-- NEW: pick up START
    end_i: int = cfg["END"]              # <-- NEW: pick up END
    log_dir = Path(cfg["LOG_DIR"])
    log_dir.mkdir(parents=True, exist_ok=True)

    if not methods:
        print("Error: no methods provided (use --methods or config).", file=sys.stderr)
        sys.exit(1)
    if not gen_method:
        print("Error: GEN_METHOD could not be determined.", file=sys.stderr)
        sys.exit(1)

    print("Using methods:", " ".join(methods))
    print("Generator method:", gen_method)
    print("Models:", " ".join(models))
    print("Mode:", mode)
    print(f"Config: base_dir={base_dir}, names={names}")

    # For each NAME:
    #   1) Submit generator job (eval_sbatch.sh gen_method ... -- <extra>)
    #   2) For methods != gen_method, submit a small copy job that depends on generator.
    #   3) Submit grade jobs:
    #        - gen_method grading depends on generator
    #        - other methods grading depends on their copy job
    #
    # Everything is launched immediately; SLURM dependencies enforce correct order.
    
    for name in names:
        # -------- 1) generator job --------
        gen_jobid = None
        args.skip_gen = False
        if not args.skip_gen:
            gen_args = [
                f"--partition={partition}",
                f"--job-name=gen_{name}_{gen_method}",
                f"--output={log_dir}/gen_{name}_{gen_method}_%j.out",
                f"--error={log_dir}/gen_{name}_{gen_method}_%j.err",
                "scripts/eval_sbatch.sh", gen_method,
                "--base", base_dir,
                "--name", name,
                "--models", *models,
                "--log_level", log_level,
                "--mode", mode,
                "--slice", str(start_i), str(end_i),  # <-- NEW: pass slice to eval side
                "--", *extra
            ]
            gen_jobid = submit(gen_args)
            print(f"[{name}] submitted generator: {gen_jobid}")

            # -------- 2) copy jobs for non-gen methods --------
            copy_jobids: Dict[str, str] = {}
            gen_results_dir = Path(base_dir) / f"results_{name}_{gen_method}" / mode

            for m in methods:
                if m == gen_method:
                    continue
                # Build a bash copy command that mirrors the bash script's copy loop
                # Copy for each model: {gen_results_dir}/{model}/responses/{model}_final_responses.json
                # -> {base_dir}/results_{name}_{m}/{mode}/{model}/responses/
                copy_cmd_parts = []
                for model in models:
                    src = gen_results_dir / model / "responses" / f"{model}_final_responses.json"
                    dest_dir = Path(base_dir) / f"results_{name}_{m}" / mode / model / "responses"
                    # mkdir -p && cp -f
                    copy_cmd_parts.append(f"mkdir -p {shlex.quote(str(dest_dir))}")
                    copy_cmd_parts.append(f"cp -f {shlex.quote(str(src))} {shlex.quote(str(dest_dir))}/")
                wrapped = " && ".join(copy_cmd_parts) if copy_cmd_parts else "true"

                copy_args = [
                    f"--partition={partition}",
                    f"--job-name=copy_{name}_{m}",
                    f"--output={log_dir}/copy_{name}_{m}_%j.out",
                    f"--error={log_dir}/copy_{name}_{m}_%j.err",
                    f"--dependency=afterok:{gen_jobid}",
                    "--wrap", wrapped
                ]
                copy_jobid = submit(copy_args)
                copy_jobids[m] = copy_jobid
                print(f"[{name}] submitted copy for {m}: {copy_jobid} (dep on gen {gen_jobid})")

        # -------- 3) grading jobs --------
        for m in methods:
            if gen_jobid is not None:
                dep = gen_jobid if m == gen_method else copy_jobids[m]
                grade_args = [
                    f"--partition={partition}",
                    f"--job-name=grade_{name}_{m}",
                    f"--output={log_dir}/grade_{name}_{m}_%j.out",
                    f"--error={log_dir}/grade_{name}_{m}_%j.err",
                    f"--dependency=afterok:{dep}",
                    "scripts/grade_sbatch.sh", m,
                    "--base", base_dir,
                    "--name", name,
                    "--models", *models,
                    "--log_level", log_level,
                    "--slice", str(start_i), str(end_i),  # <-- NEW: pass slice to eval side
                    "--mode", mode,
                    "--", *extra
                ]
            else:
                dep = "nothing"
                grade_args = [
                    f"--partition={partition}",
                    f"--job-name=grade_{name}_{m}",
                    f"--output={log_dir}/grade_{name}_{m}_%j.out",
                    f"--error={log_dir}/grade_{name}_{m}_%j.err",
                    "scripts/grade_sbatch.sh", m,
                    "--base", base_dir,
                    "--name", name,
                    "--models", *models,
                    "--log_level", log_level,
                    "--slice", str(start_i), str(end_i),  # <-- NEW: pass slice to eval side
                    "--mode", mode,
                    "--", *extra
                ]
            grade_jobid = submit(grade_args)
            print(f"[{name}] submitted grade for {m}: {grade_jobid} (dep on {dep})")

if __name__ == "__main__":
    main()
