#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Export key information (problem context, reference solution, student answer) to Markdown.

Input items are expected to look like:
{
  "id": "12345",
  "problem": {..., "solution": "... (markdown) ..."},
  "grade_1": {"score": 0.7, "answer": "... (markdown) ...", ...},
  "grade_2": {"score": 0.8, "answer": "... (markdown) ...", ...}
}

We call utils.prompt_utils.get_problem_context(problem) which returns Markdown.
"""

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

def load_json_or_jsonl(path: Path) -> List[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data["items"]
        raise ValueError(f"{path}: unsupported JSON structure (expected list or {{'items': list}}).")
    except json.JSONDecodeError:
        out: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

def ensure_str_md(x: Any) -> str:
    """Return a string suitable for Markdown insertion."""
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    # Fallback: pretty JSON if a dict/list sneaks in
    return json.dumps(x, ensure_ascii=False, indent=2)

def main():
    ap = argparse.ArgumentParser(description="Export sampled compare items to a Markdown file for annotation.")
    ap.add_argument("--in", dest="inp", type=Path, required=True,
                    help="Input JSON/JSONL file (array with keys: id, problem, grade_1, grade_2)")
    ap.add_argument("--out", type=Path, required=True,
                    help="Output Markdown path")
    ap.add_argument("--answers-from", choices=["1", "2", "auto"], default="1",
                    help="Which grade to pull 'answer' from. 'auto' uses 1 then falls back to 2.")
    ap.add_argument("--add-pythonpath", type=Path, default=None,
                    help="Optional path added to sys.path so 'utils.prompt_utils' can be imported")
    ap.add_argument("--title", default="Annotation Packet",
                    help="Top-level title in the Markdown")
    ap.add_argument("--show-original-scores", action="store_true",
                    help="Include original scores from grade_1 and grade_2")
    ap.add_argument("--section-start-index", type=int, default=1,
                    help="Start numbering sections from this index (default: 1)")
    args = ap.parse_args()

    if args.add_pythonpath:
        sys.path.insert(0, str(args.add_pythonpath))

    try:
        prompt_utils = importlib.import_module("utils.prompt_utils")
    except Exception as e:
        print(f"[ERROR] Could not import utils.prompt_utils. "
              f"Use --add-pythonpath to point to your repo root. Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not hasattr(prompt_utils, "get_problem_context"):
        print("[ERROR] utils.prompt_utils.get_problem_context not found.", file=sys.stderr)
        sys.exit(1)
    get_problem_context = getattr(prompt_utils, "get_problem_context")

    items = load_json_or_jsonl(args.inp)
    if not items:
        print(f"[ERROR] No items found in {args.inp}", file=sys.stderr)
        sys.exit(1)

    lines: List[str] = []
    # Title
    lines.append(f"# {args.title}")
    lines.append("")
    lines.append(f"*Source file:* `{args.inp}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    def pick_answer(obj: Dict[str, Any]) -> str:
        if args.answers_from == "1":
            return ensure_str_md((obj.get("grade_1") or {}).get("answer"))
        elif args.answers_from == "2":
            return ensure_str_md((obj.get("grade_2") or {}).get("answer"))
        else:
            a1 = (obj.get("grade_1") or {}).get("answer")
            return ensure_str_md(a1 if a1 not in (None, "") else (obj.get("grade_2") or {}).get("answer"))

    for idx, it in enumerate(items, start=args.section_start_index):
        pid = it.get("id", "")
        problem = it.get("problem") or {}
        grade_1 = it.get("grade_1") or {}
        grade_2 = it.get("grade_2") or {}

        # Render context (Markdown)
        try:
            context_md = ensure_str_md(get_problem_context(problem))
        except Exception as e:
            print(f"[WARN] get_problem_context failed for id={pid}: {e}", file=sys.stderr)
            context_md = ensure_str_md(problem)

        solution_md = ensure_str_md(problem.get("solution"))
        answer_md = pick_answer(it)

        # Header
        header = f"## {idx}. ID: `{pid}`"
        if args.show_original_scores:
            s1 = grade_1.get("score")
            s2 = grade_2.get("score")
            header += f"  —  Original scores: run1={s1}, run2={s2}"
        lines.append(header)
        lines.append("")
        # Problem Context (insert Markdown verbatim)
        lines.append("**Problem Context**")
        lines.append("")
        lines.append(context_md)
        lines.append("")
        # Reference Solution (Markdown)
        lines.append("**Reference Solution**")
        lines.append("")
        lines.append(solution_md)
        lines.append("")
        # Student Answer (Markdown)
        lines.append("**Student Answer**")
        lines.append("")
        lines.append(answer_md)
        lines.append("")
        lines.append("---")
        lines.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[OK] Wrote Markdown for {len(items)} items -> {args.out}")

if __name__ == "__main__":
    main()
