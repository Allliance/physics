#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List

def build_set_ids(start: int, end: int, pad: int, explicit: List[str]) -> List[str]:
    if explicit:
        out = []
        for s in explicit:
            s = s.strip()
            if not s:
                continue
            if s.isdigit():
                out.append(s.zfill(pad))
            else:
                out.append(s)  # use as-is if already like '01'
        return out
    return [str(i).zfill(pad) for i in range(start, end + 1)]

def main():
    p = argparse.ArgumentParser(
        description="Launch compare_score.py across multiple problem sets."
    )
    p.add_argument("--compare-script", type=Path, default=Path("Analyze_framework/compare_score.py"),
                   help="Path to compare_score.py")
    p.add_argument("--main-root", type=Path, default=Path("main_exp"),
                   help="Root containing results_* folders and problem JSONs")
    p.add_argument("--out-root", type=Path, default=Path("Analyze_framework/main_exp_deepseek_v3"),
                   help="Where to write {set}_compare.json files")
    p.add_argument("--model", default="deepseek-v3",
                   help="Model subfolder under text/, e.g., 'deepseek-v3'")
    p.add_argument("--start", type=int, default=1, help="First set index (inclusive)")
    p.add_argument("--end", type=int, default=7, help="Last set index (inclusive)")
    p.add_argument("--pad", type=int, default=2, help="Zero-padding width for set IDs")
    p.add_argument("--sets", nargs="*", default=None,
                   help="Explicit set IDs (e.g., 01 03 07). If provided, --start/--end are ignored.")
    p.add_argument("--atol", type=float, default=1e-6, help="Abs tolerance for numeric score equality")
    p.add_argument("--warn-mismatch-problem-id", action="store_true",
                   help="Pass through to compare_score.py to warn if grade['problem_id'] != filename id")
    p.add_argument("--continue-on-error", action="store_true",
                   help="Keep going even if one invocation fails")
    args = p.parse_args()

    sets = build_set_ids(args.start, args.end, args.pad, args.sets or [])

    # Basic checks
    if not args.compare_script.exists():
        print(f"[ERROR] compare script not found: {args.compare_script}", file=sys.stderr)
        sys.exit(1)

    args.out_root.mkdir(parents=True, exist_ok=True)

    results = []
    for sid in sets:
        grades_dir_1 = args.main_root / f"results_{sid}_dag" / "text" / args.model / "grades" / "dag"
        grades_dir_2 = args.main_root / f"results_{sid}_seephys" / "text" / args.model / "grades" / "seephys"
        problems = args.main_root / f"{sid}_dag.json"
        out_path = args.out_root / f"{sid}_compare.json"

        # Informative header
        print("=" * 80)
        print(f"[RUN] Set {sid}")
        print(f"  grades_dir_1: {grades_dir_1}")
        print(f"  grades_dir_2: {grades_dir_2}")
        print(f"  problems:     {problems}")
        print(f"  out:          {out_path}")
        print("-" * 80)

        # Ensure parents for out exist
        out_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,  # use same interpreter
            str(args.compare_script),
            "--grades_dir_1", str(grades_dir_1),
            "--grades_dir_2", str(grades_dir_2),
            "--problems", str(problems),
            "--out", str(out_path),
            "--output-format", "json",
            "--atol", str(args.atol),
        ]
        if args.warn_mismatch_problem_id:
            cmd.append("--warn-mismatch-problem-id")

        try:
            # Stream output directly so you see the per-set counts
            rc = subprocess.run(cmd, check=False).returncode
            results.append((sid, rc))
            if rc != 0:
                msg = f"[FAIL] Set {sid} exited with code {rc}"
                if args.continue_on_error:
                    print(msg, file=sys.stderr)
                else:
                    print(msg, file=sys.stderr)
                    break
        except Exception as e:
            results.append((sid, 1))
            msg = f"[EXCEPTION] Set {sid} raised: {e}"
            if args.continue_on_error:
                print(msg, file=sys.stderr)
                continue
            else:
                print(msg, file=sys.stderr)
                break

    print("=" * 80)
    print("[SUMMARY]")
    ok = [sid for sid, rc in results if rc == 0]
    bad = [(sid, rc) for sid, rc in results if rc != 0]
    print(f"Successful sets: {ok}")
    if bad:
        print(f"Failed sets: {bad} (see logs above)")
    else:
        print("No failures.")

if __name__ == "__main__":
    main()
