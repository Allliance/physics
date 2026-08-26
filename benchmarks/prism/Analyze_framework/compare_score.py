#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Dict, Any, Iterable, Tuple, List, Optional

SUFFIX = "_grade.json"

def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def load_jsonl(path: Path) -> List[Any]:
    items = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items

def load_problems_map(problems_path: Path) -> Dict[str, Any]:
    """
    Supports:
      - JSON array of problem objects
      - JSONL (one JSON object per line)
      - JSON object with key 'items' that is a list of problems
    Returns {str(id): problem_object}
    """
    problems: List[Dict[str, Any]] = []
    try:
        data = load_json(problems_path)
        if isinstance(data, list):
            problems = data
        elif isinstance(data, dict):
            if isinstance(data.get("items"), list):
                problems = data["items"]
            else:
                # Heuristic: pick the first list value that looks like a list of dicts with 'id'
                for v in data.values():
                    if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                        problems = v
                        break
                if not problems:
                    raise ValueError("Problems file JSON object did not contain a list of problems.")
        else:
            raise ValueError("Problems file must be a JSON array or object.")
    except json.JSONDecodeError:
        # Try JSONL
        problems = load_jsonl(problems_path)

    prob_map: Dict[str, Any] = {}
    for p in problems:
        if isinstance(p, dict) and "id" in p:
            prob_map[str(p["id"])] = p
    if not prob_map:
        raise ValueError("Parsed problems file but found no items with an 'id'.")
    return prob_map

def iter_grade_files(dir_path: Path) -> Iterable[Tuple[str, Path]]:
    """
    Yields (id_str, file_path) for files ending with '_grade.json' in the directory (non-recursive).
    """
    for p in dir_path.iterdir():
        if p.is_file() and p.name.endswith(SUFFIX):
            id_str = p.name[: -len(SUFFIX)]
            if id_str:  # ignore weird names like '_grade.json'
                yield id_str, p

def truthy(x: Any) -> bool:
    return bool(x) and x not in (0, "", False, None)

def has_error(grade_obj: Dict[str, Any]) -> bool:
    # Consider any present 'error' value that is truthy as an error; also treat missing score as error.
    if "error" in grade_obj and truthy(grade_obj.get("error")):
        return True
    if "score" not in grade_obj:
        return True
    return False

def to_number_or_none(x: Any) -> Optional[float]:
    try:
        # Accept ints, floats, or numeric strings
        return float(x)
    except Exception:
        return None

def compare_scores(s1: Any, s2: Any, atol: float) -> bool:
    """
    Returns True if 'equal' within rules:
      - if both numeric: use math.isclose with abs tol
      - else: use == exact equality
    """
    n1 = to_number_or_none(s1)
    n2 = to_number_or_none(s2)
    if n1 is not None and n2 is not None:
        return math.isclose(n1, n2, rel_tol=0.0, abs_tol=atol)
    return s1 == s2

def main():
    parser = argparse.ArgumentParser(description="Compare grade files across two folders and collect differing scores.")
    parser.add_argument("--grades_dir_1", required=True, type=Path, help="Path to first grades directory")
    parser.add_argument("--grades_dir_2", required=True, type=Path, help="Path to second grades directory")
    parser.add_argument("--problems", required=True, type=Path, help="Path to problems file (JSON array / JSONL / dict with 'items')")
    parser.add_argument("--out", required=True, type=Path, help="Output file to write unequal-score records")
    parser.add_argument("--output-format", choices=["jsonl", "json"], default="jsonl", help="Output format (default: jsonl)")
    parser.add_argument("--atol", type=float, default=1e-9, help="Absolute tolerance for numeric score equality (default: 1e-9)")
    parser.add_argument("--warn-mismatch-problem-id", action="store_true",
                        help="If set, warn (stderr) when grade['problem_id'] doesn't match filename id.")
    args = parser.parse_args()

    g1 = {id_str: path for id_str, path in iter_grade_files(args.grades_dir_1)}
    g2 = {id_str: path for id_str, path in iter_grade_files(args.grades_dir_2)}
    shared_ids = sorted(set(g1).intersection(g2))

    if not shared_ids:
        print("No shared IDs found between the two grade folders.", file=sys.stderr)
        print("Different: 0\nSame: 0\nErrors: 0")
        return

    # Load problems and check coverage
    prob_map = load_problems_map(args.problems)
    missing_in_problems = [sid for sid in shared_ids if sid not in prob_map]
    if missing_in_problems:
        raise RuntimeError(
            f"The following shared IDs are missing from the problems file: {missing_in_problems[:10]} "
            f"{'(and more...)' if len(missing_in_problems) > 10 else ''}"
        )

    # Prepare output writer
    records: List[Dict[str, Any]] = []
    out_fp = None
    if args.output_format == "jsonl":
        out_fp = args.out.open("w", encoding="utf-8")

    different = 0
    same = 0
    errors = 0

    for sid in shared_ids:
        p1 = g1[sid]
        p2 = g2[sid]
        try:
            grade1 = load_json(p1)
            grade2 = load_json(p2)
        except Exception as e:
            # If a file can't be read/parsed, treat as error
            errors += 1
            print(f"[WARN] Failed to load JSON for id={sid}: {e}", file=sys.stderr)
            continue

        if args.warn_mismatch_problem_id:
            pid1 = str(grade1.get("problem_id"))
            pid2 = str(grade2.get("problem_id"))
            if pid1 and pid1 != sid:
                print(f"[WARN] grades_dir_1 id='{sid}' but grade['problem_id']='{pid1}'", file=sys.stderr)
            if pid2 and pid2 != sid:
                print(f"[WARN] grades_dir_2 id='{sid}' but grade['problem_id']='{pid2}'", file=sys.stderr)

        if has_error(grade1) or has_error(grade2):
            errors += 1
            continue

        s1 = grade1.get("score")
        s2 = grade2.get("score")

        if compare_scores(s1, s2, atol=args.atol):
            same += 1
            continue

        # Different
        different += 1
        record = {
            "id": sid,
            "problem": prob_map[sid],
            "grade_1": grade1,
            "grade_2": grade2,
        }
        if args.output_format == "jsonl":
            out_fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        else:
            records.append(record)

    if args.output_format == "json":
        with args.out.open("w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
    elif out_fp is not None:
        out_fp.close()

    print(f"Shared IDs considered: {len(shared_ids)}")
    print(f"Different scores: {different}")
    print(f"Same scores: {same}")
    print(f"Ignored due to error: {errors}")

if __name__ == "__main__":
    main()
