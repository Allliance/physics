#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

def main():
    gen = Path("gen_md_single.py")     # adjust if needed
    base = Path("main_exp_deepseek_v3")

    if not gen.exists():
        print(f"Generator not found: {gen}", file=sys.stderr)
        sys.exit(1)

    for i in range(1, 8):
        tag = f"{i:02d}"
        in_json = base / f"{tag}_compare.json"
        out_dir = base / tag

        if not in_json.exists():
            print(f">> Skipping {tag}: input not found: {in_json}", file=sys.stderr)
            continue

        out_dir.mkdir(parents=True, exist_ok=True)

        print(f">> Processing {in_json} -> {out_dir}")
        cmd = [
            sys.executable, str(gen),
            "--input_json", str(in_json),
            "--outdir_a", str(out_dir),
            "--outdir_b", str(out_dir),
            "--sample_num", "20"
        ]
        # Run and stream output
        subprocess.run(cmd, check=True)

    print("All done.")

if __name__ == "__main__":
    main()
