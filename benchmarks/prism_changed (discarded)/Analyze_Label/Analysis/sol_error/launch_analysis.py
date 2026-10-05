import argparse
import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# -----------------------
# Utils
# -----------------------

def sanitize(s: str) -> str:
    s = s.strip().replace("/", "_").replace(":", "_")
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", s)

def expand(s: Optional[str]) -> Optional[str]:
    return None if s is None else os.path.expandvars(os.path.expanduser(s))

def try_load_config(path: Optional[str]) -> Dict[str, Any]:
    """Load JSON/YAML config if present; return {} if not found or --no-config."""
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        if p.suffix.lower() in {".yaml", ".yml"}:
            try:
                import yaml  # type: ignore
            except Exception as e:
                raise RuntimeError(
                    f"Config '{p}' is YAML but PyYAML is not installed. "
                    "Install pyyaml or use JSON."
                ) from e
            with p.open("r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        else:
            with p.open("r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception as e:
        raise RuntimeError(f"Failed to load config '{p}': {e}") from e

def cli_overrides(cfg: Dict[str, Any], ns: argparse.Namespace) -> Dict[str, Any]:
    """Return merged settings where CLI (when provided) overrides config."""
    out = dict(cfg)

    def set_if_provided(key: str, attr: str = None):
        k = attr or key
        val = getattr(ns, k)
        # Lists default to [], scalars default to None; only override if user provided something truthy or explicitly provided empty list.
        provided = (val is not None) if not isinstance(val, list) else (val != [])
        if provided:
            out[key] = val

    # Scalars / lists that can override
    set_if_provided("problem_sets")
    set_if_provided("models")
    set_if_provided("method")
    set_if_provided("processes")
    set_if_provided("partition")
    set_if_provided("time")
    set_if_provided("cpus")
    set_if_provided("mem")
    set_if_provided("gres")
    set_if_provided("account")
    set_if_provided("dependency")
    set_if_provided("extra_sbatch")
    set_if_provided("log_dir")
    set_if_provided("analyze_model")

    # matrix override behaves like others
    set_if_provided("matrix")

    return out

def validate_settings(s: Dict[str, Any]) -> None:
    if "matrix" in s and s["matrix"]:
        # matrix rows must have at least problem_set & model; method falls back to global or "dag"
        if not isinstance(s["matrix"], list):
            raise ValueError("config.matrix must be a list of {problem_set, model, [method]} objects.")
        for row in s["matrix"]:
            if not isinstance(row, dict) or "problem_set" not in row or "model" not in row:
                raise ValueError("Each matrix row must be a dict containing 'problem_set' and 'model'.")
    else:
        if not s.get("problem_sets"):
            raise ValueError("No problem sets specified (config or CLI).")
        if not s.get("models"):
            raise ValueError("No models specified (config or CLI).")

def make_paths(pset: str, model: str, method: str, mode: str = "text") -> Tuple[str, str, str]:
    grades_glob = f"main_exp/results_{pset}_{method}/{mode}/{model}/grades/{method}/*_grade.json"
    problems_json = f"main_exp/{pset}_{method}.json"
    outdir = f"Analyze_Label/Analysis/sol_error/{model}/results_{pset}_{method}"
    return grades_glob, problems_json, outdir

def build_wrap_command(grades_glob: str, problems_json: str, outdir: str,
                       model_for_analyze: str, processes: int) -> str:
    cmd = [
        "python", "-m", "Analyze_Label.Analysis.sol_error.analyze",
        "--grades", grades_glob,
        "--problems", problems_json,
        "--outdir", outdir,
        "--model", model_for_analyze,
        "--processes", str(processes),
    ]
    return " ".join(shlex.quote(x) for x in cmd)

def submit_one(settings: Dict[str, Any], pset: str, model: str, method: str, dry_run: bool = False) -> Optional[str]:
    grades_glob, problems_json, outdir = make_paths(pset, model, method)
    wrap = build_wrap_command(
        grades_glob, problems_json, outdir,
        settings.get("analyze_model") or model,
        int(settings.get("processes", 32)),
    )

    log_dir = Path(expand(settings.get("log_dir") or "logs/analyze"))
    log_dir.mkdir(parents=True, exist_ok=True)

    job_name = f"an_{method}_{sanitize(pset)}_{sanitize(model)}"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    sbatch_cmd = [
        "sbatch",
        f"--job-name={job_name}",
        f"--partition={settings.get('partition', 'jamesz')}",
        f"--time={settings.get('time', '04:00:00')}",
        f"--cpus-per-task={int(settings.get('cpus', 8))}",
        f"--mem={settings.get('mem', '8G')}",
        f"--output={log_dir}/{job_name}_{ts}_%j.out",
        f"--error={log_dir}/{job_name}_{ts}_%j.err",
        "--export=ALL",
    ]

    if settings.get("gres"):
        sbatch_cmd.append(f"--gres={settings['gres']}")
    if settings.get("account"):
        sbatch_cmd.append(f"--account={settings['account']}")
    if settings.get("dependency"):
        sbatch_cmd.append(f"--dependency={settings['dependency']}")
    if settings.get("extra_sbatch"):
        sbatch_cmd.extend(shlex.split(settings["extra_sbatch"]))

    sbatch_cmd += ["--wrap", f"bash -lc {shlex.quote(wrap)}"]

    if dry_run:
        print("[DRY-RUN]", " ".join(shlex.quote(x) for x in sbatch_cmd))
        return None

    sbatch_cmd_with_parsable = sbatch_cmd[:1] + ["--parsable"] + sbatch_cmd[1:]
    proc = subprocess.run(sbatch_cmd_with_parsable, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"[ERROR] sbatch failed for {job_name}:\n{proc.stderr.strip()}")
        return None
    jobid = proc.stdout.strip()
    print(f"[SUBMITTED] {job_name} -> JobID {jobid}")
    return jobid

# -----------------------
# CLI
# -----------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Submit sol_error analyses via sbatch (config + CLI override).")
    # Matrix or product inputs
    ap.add_argument("--problem-sets", nargs="+", default=[],
                    help="Problem set IDs like 01 02 03 (used as '01_<method>').")
    ap.add_argument("--models", nargs="+", default=[],
                    help="Model names (used in paths).")
    ap.add_argument("--method", default=None, choices=["dag", "tree", "seephys"],
                    help="Sub-benchmark; if omitted, uses config or defaults to 'dag'.")
    ap.add_argument("--matrix", nargs="+", default=[],
                    help="Explicit matrix rows as JSON strings, e.g. "
                         "'{\"problem_set\":\"01\",\"model\":\"gpt-4.1\",\"mode\":\"dag\"}'")

    # Analyzer + resources
    ap.add_argument("--analyze-model", default=None)
    ap.add_argument("--processes", type=int, default=None)
    ap.add_argument("--partition", default=None)
    ap.add_argument("--time", default=None)
    ap.add_argument("--cpus", type=int, default=None)
    ap.add_argument("--mem", default=None)
    ap.add_argument("--gres", default=None)
    ap.add_argument("--account", default=None)
    ap.add_argument("--dependency", default=None)
    ap.add_argument("--extra-sbatch", default=None)
    ap.add_argument("--log-dir", default=None)

    # Config controls
    ap.add_argument("--config", default="Analyze_Label/Analysis/sol_error/config.json",
                    help="Path to config file (JSON/YAML).")
    ap.add_argument("--no-config", action="store_true",
                    help="Ignore config file entirely.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print sbatch commands without submitting.")
    return ap.parse_args()

def main():
    args = parse_args()

    # Load config (unless disabled)
    cfg_path = None if args.no_config else args.config
    cfg = try_load_config(cfg_path) if cfg_path else {}

    # If --matrix is given via CLI, parse into objects and let it override config.matrix
    matrix_cli = []
    for m in args.matrix:
        try:
            matrix_cli.append(json.loads(m))
        except json.JSONDecodeError as e:
            raise SystemExit(f"--matrix entry is not valid JSON: {m}\n{e}")
    if matrix_cli:
        cfg["matrix"] = matrix_cli

    # Merge: CLI overrides config where provided
    settings = cli_overrides(cfg, args)

    # Defaults for fields not present anywhere
    settings.setdefault("method", "dag")
    settings.setdefault("processes", 74)
    settings.setdefault("partition", "jamesz")
    settings.setdefault("time", "8:00:00")
    settings.setdefault("cpus", 4)
    settings.setdefault("mem", "10G")
    settings.setdefault("log_dir", "logs/analyze")

    # Validate
    validate_settings(settings)

    # Build job list
    jobs: List[Tuple[str, str, str]] = []
    if settings.get("matrix"):
        for row in settings["matrix"]:
            pset = row["problem_set"]
            model = row["model"]
            method = row.get("method", settings["method"])
            jobs.append((pset, model, method))
    else:
        for pset in settings["problem_sets"]:
            for model in settings["models"]:
                jobs.append((pset, model, settings["method"]))

    # Submit
    jobids: List[str] = []
    for pset, model, method in jobs:
        jid = submit_one(settings, pset, model, method, dry_run=args.dry_run)
        if jid:
            jobids.append(jid)

    if args.dry_run:
        print("\n[DRY-RUN] Done. No jobs submitted.")
    else:
        print("\nSummary:")
        if jobids:
            for j in jobids:
                print("  JobID", j)
        else:
            print("  No jobs submitted.")

if __name__ == "__main__":
    main()