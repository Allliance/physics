#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, List, Dict, Optional

def load_json_or_jsonl(path: Path) -> List[Any]:
    """Load a list of items from JSON array, JSONL, or dict with 'items'."""
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if isinstance(data.get("items"), list):
                return data["items"]
            # fallback: look for any list-of-dicts value
            for v in data.values():
                if isinstance(v, list):
                    return v
        raise ValueError(f"{path}: unsupported JSON structure.")
    except json.JSONDecodeError:
        # try JSONL
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    items.append(json.loads(line))
        return items

def build_default_files(in_dir: Path, start: int, end: int, pad: int, pattern: str) -> List[Path]:
    files = []
    for i in range(start, end + 1):
        sid = str(i).zfill(pad)
        files.append(in_dir / pattern.format(id=sid, sid=sid))
    return files

def sample_from_file(path: Path, k: int, rng: random.Random, strict: bool) -> List[Any]:
    items = load_json_or_jsonl(path)
    n = len(items)
    if n == 0:
        if strict:
            raise RuntimeError(f"{path} contains 0 items.")
        print(f"[WARN] {path} has 0 items; sampling 0.", file=sys.stderr)
        return []
    if n < k:
        if strict:
            raise RuntimeError(f"{path} has only {n} items (< {k}). Use --non-strict to accept fewer.")
        print(f"[WARN] {path} has only {n} items; taking all.", file=sys.stderr)
        k = n
    # deterministic sample with given seed
    idxs = rng.sample(range(n), k)
    return [items[i] for i in idxs]

def maybe_annotate(items: List[Dict[str, Any]], source: str, annotate: bool) -> List[Dict[str, Any]]:
    if not annotate:
        return items
    out = []
    for x in items:
        if isinstance(x, dict):
            y = dict(x)
            y["_source_file"] = source
            out.append(y)
        else:
            out.append(x)
    return out

def dedup_items(items: List[Any], key: str) -> List[Any]:
    seen = set()
    out = []
    for x in items:
        if isinstance(x, dict) and key in x:
            k = x[key]
            if k in seen:
                continue
            seen.add(k)
        out.append(x)
    return out

def main():
    ap = argparse.ArgumentParser(description="Sample N items from each compare file and merge.")
    ap.add_argument("--in-dir", type=Path, default=Path("Analyze_framework/main_exp_deepseek_v3"),
                    help="Directory containing {sid}_compare.json files")
    ap.add_argument("--files", nargs="*", default=None,
                    help="Explicit list of input files. If provided, --in-dir/start/end/pad/pattern are ignored.")
    ap.add_argument("--start", type=int, default=1, help="First set id (inclusive)")
    ap.add_argument("--end", type=int, default=7, help="Last set id (inclusive)")
    ap.add_argument("--pad", type=int, default=2, help="Zero padding for set id")
    ap.add_argument("--pattern", default="{sid}_compare.json",
                    help="Filename pattern inside --in-dir; placeholders: {sid} or {id}")
    ap.add_argument("--per-file", type=int, default=20, help="Samples per file (without replacement)")
    ap.add_argument("--seed", type=int, default=20250901, help="Random seed (explicit)")
    ap.add_argument("--out", type=Path, default=Path("Analyze_framework/main_exp_deepseek_v3/sample_merged.json"),
                    help="Output JSON file (array)")
    ap.add_argument("--shuffle-merged", action="store_true",
                    help="Shuffle the merged list before writing (uses same seed)")
    ap.add_argument("--strict", dest="strict", action="store_true", help="Error if a file has < per-file items")
    ap.add_argument("--non-strict", dest="strict", action="store_false", help="Allow fewer if not enough items")
    ap.set_defaults(strict=False)
    ap.add_argument("--annotate-source", action="store_true",
                    help="Add '_source_file' to each sampled item")
    ap.add_argument("--dedup-by", default=None,
                    help="Optional key to deduplicate merged items by (e.g., 'id'). Keeps first occurrence.")
    args = ap.parse_args()

    rng = random.Random(args.seed)

    files = [Path(f) for f in args.files] if args.files else build_default_files(
        args.in_dir, args.start, args.end, args.pad, args.pattern
    )

    if not files:
        print("[ERROR] No input files resolved.", file=sys.stderr)
        sys.exit(1)

    resolved = []
    for p in files:
        if not p.exists():
            print(f"[ERROR] Missing file: {p}", file=sys.stderr)
            sys.exit(1)
        resolved.append(p)

    merged: List[Any] = []
    total_expected = 0
    for p in resolved:
        take = args.per_file
        sampled = sample_from_file(p, take, rng, args.strict)
        total_expected += min(take, len(load_json_or_jsonl(p)))
        sampled = maybe_annotate(sampled, str(p), args.annotate_source)
        merged.extend(sampled)
        print(f"[OK] {p.name}: sampled {len(sampled)} items.", file=sys.stderr)

    if args.dedup_by:
        before = len(merged)
        merged = dedup_items(merged, args.dedup_by)
        after = len(merged)
        print(f"[INFO] Deduplicated by '{args.dedup_by}': {before} -> {after}", file=sys.stderr)

    if args.shuffle_merged:
        rng.shuffle(merged)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"Input files: {len(resolved)}", file=sys.stderr)
    print(f"Merged items: {len(merged)}", file=sys.stderr)
    print(f"Wrote: {args.out}")

if __name__ == "__main__":
    main()
