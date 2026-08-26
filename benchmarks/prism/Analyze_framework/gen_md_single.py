#!/usr/bin/env python3
# save_items_to_md.py
import argparse
import json
import re
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Tuple

# ---------- helpers ----------

def to_list(x: Union[List[Any], Any]) -> List[Any]:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]

def remove_unit(s: str) -> str:
    # strip \unit{...} but keep inner
    return re.sub(r'\\unit\{([^}]*)\}', r'\1', s)

def add_score_placeholder(s: str) -> str:
    return (
        s
        + "\n\n## Scoring\n"
        + "**Score (100 pts max)**: 50% score=[], 16% score = [], 84% score = [].\n"
        + "(16% score <= 50% score <= 84% score)\n\n"
        + "(Note that for normal distribution, mean, mean-std, mean+std corresponds to 50% score, 16% score and 84% score).\n"
    )

def render_images(images: List[Dict[str, Any]]) -> str:
    if not images:
        return ""
    lines = ["\n## Images"]
    for img in images:
        cap = (img.get("caption") or "").strip()
        loc = (img.get("location") or "").strip()
        if loc:
            alt = cap or Path(loc).name
            lines.append(f"\n![{alt}]({loc})")
            if cap:
                lines.append(f"\n*{cap}*")
    return "\n".join(lines) + "\n"

# ---------- schema detection / normalization ----------

def has_duplicate_grades(item: Dict[str, Any]) -> bool:
    g1 = (item.get("grade_1") or {}).get("score", -1)
    g2 = (item.get("grade_2") or {}).get("score", -1)
    return g1 < 0 or g2 < 0 or g1 == g2

def detect_schema(item: Dict[str, Any]) -> str:
    if isinstance(item.get("problem"), dict):
        return "nested"   # your new schema
    if "problem_id" in item and "response" in item:
        return "flat"     # old schema
    if "response" in item and ("id" in item or "problem_id" in item):
        return "flat"
    return "unknown"

def compute_output_id(item: Dict[str, Any]) -> str:
    if isinstance(item.get("problem"), dict):
        p = item["problem"]
        return str(p.get("id") if p.get("id") is not None else item.get("id", ""))
    return str(item.get("problem_id", item.get("id", "")))

def pick_student_answer(item: Dict[str, Any]) -> str:
    # Prefer grade_1.answer, then grade_2.answer, else any grade_*.answer
    for key in ("grade_1", "grade_2"):
        ans = (item.get(key, {}) or {}).get("answer")
        if isinstance(ans, str) and ans.strip():
            return ans
    for k, v in item.items():
        if isinstance(v, dict) and k.startswith("grade_"):
            ans = v.get("answer")
            if isinstance(ans, str) and ans.strip():
                return ans
    return ""

def extract_problem_view(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a normalized 'problem view' dict with keys:
    id, source, context, images, subquestions, solution, grading_standard
    Works for nested (preferred) and makes a best effort for flat.
    """
    schema = detect_schema(item)
    if schema == "nested":
        p = item.get("problem", {}) or {}
        return {
            "id": p.get("id", item.get("id", "")),
            "source": p.get("source", ""),
            "context": p.get("context", ""),
            "images": to_list(p.get("images")),
            "subquestions": to_list(p.get("subquestions")),
            "solution": p.get("solution", ""),  # sometimes top-level problems have a single solution
            "grading_standard": to_list(p.get("grading_standard")),
        }
    # flat fallback
    return {
        "id": item.get("problem_id", item.get("id", "")),
        "source": item.get("source", ""),
        "context": item.get("response", "") or item.get("context", ""),
        "images": to_list(item.get("images")),
        "subquestions": to_list(item.get("subquestions")),
        "solution": item.get("solution", ""),
        "grading_standard": to_list(item.get("grading_standard")),
    }

# ---------- A-style rendering (rich, scorer) ----------

def render_nested_problem_for_A(problem: Dict[str, Any]) -> str:
    pid = problem.get("id", "")
    source = problem.get("source", "")
    context = (problem.get("context") or "").rstrip()
    images = to_list(problem.get("images"))
    subqs = to_list(problem.get("subquestions"))

    out: List[str] = []
    title = f"# Problem {pid}" + (f" — {source}" if source else "")
    out.append(title)

    if context:
        out.append("\n\n## Context\n\n")
        out.append(context + "\n")

    img_block = render_images(images)
    if img_block:
        out.append(img_block)

    if subqs:
        for sq in subqs:
            letter = (sq.get("letter") or "").strip()
            header = f"## Subproblem ({letter})" if letter else "## Subproblem"
            out.append("\n" + header + "\n\n")
            subtext = (sq.get("subproblem") or "").rstrip()
            if subtext:
                out.append(subtext + "\n")
            sol = (sq.get("solution") or "").rstrip()
            if sol:
                out.append("\n### Reference Solution\n\n")
                out.append(sol + "\n")
    else:
        sol = (problem.get("solution") or "").rstrip()
        if sol:
            out.append("\n## Reference Solution\n\n")
            out.append(sol + "\n")

    # NOTE: Removed "## Grading Standard (Formulas)" section per request.
    return "".join(out).rstrip() + "\n"

def _truncate(s: str, n: int = 180) -> str:
    s = str(s)
    return s[:n] + ("…" if len(s) > n else "")

def _format_matches(matches_obj) -> str:
    lines = []
    if matches_obj is None:
        return ""
    if isinstance(matches_obj, (str, dict)):
        seq = [matches_obj]
    else:
        try:
            iter(matches_obj)
            seq = matches_obj
        except TypeError:
            seq = [matches_obj]

    for m in seq:
        if isinstance(m, dict):
            std_eq = m.get("std_equation") or m.get("std") or ""
            ans_eq = m.get("answer_equation") or m.get("ans") or ""
            reason = m.get("reason") or m.get("note") or ""
            if not (std_eq or ans_eq or reason):
                reason = _truncate(m, 180)
            if std_eq or ans_eq:
                lines.append(
                    "  - std: `{}`\n    ans: `{}`\n    note: {}".format(
                        std_eq, ans_eq, _truncate(reason, 180)
                    )
                )
            else:
                lines.append("  - {}".format(_truncate(reason, 180)))
        else:
            lines.append("  - {}".format(_truncate(m, 180)))
    return "\n".join(lines)


def render_A_style(item: Dict[str, Any]) -> str:
    """Rich output + Student Answer + Auto-grader summary + Scoring box."""
    pv = extract_problem_view(item)
    main = render_nested_problem_for_A(pv)

    student_ans = pick_student_answer(item)
    if student_ans:
        main += "\n## Student Answer (verbatim)\n\n" + student_ans.strip() + "\n"

    # scoring box at the end (and strip \unit{...})
    main = remove_unit(main)
    main = add_score_placeholder(main)
    return main

# ---------- Q-and-S-style rendering (your grader-labeling flow) ----------

def render_QS_single_or_multi(pv: Dict[str, Any]) -> str:
    """Your original problems+solutions renderer (multi-aware)."""
    id_ = pv.get("id", "")
    source = pv.get("source", "")
    context = (pv.get("context") or "").rstrip()
    images = to_list(pv.get("images"))
    subqs = to_list(pv.get("subquestions"))
    sol = (pv.get("solution") or "").rstrip()

    out: List[str] = []
    title = f"# Problem {id_}" + (f" — {source}" if source else "")
    out.append(title)
    if context:
        out.append("\n## Context\n")
        out.append(context + "\n")
    img_block = render_images(images)
    if img_block:
        out.append(img_block)

    if subqs:
        for sq in subqs:
            letter = (sq.get("letter") or "").strip()
            header = f"## Subproblem ({letter})" if letter else "## Subproblem"
            out.append("\n" + header + "\n")
            prob_text = (sq.get("subproblem") or "").rstrip()
            if prob_text:
                out.append(prob_text + "\n")
            sol_s = (sq.get("solution") or "").rstrip()
            if sol_s:
                out.append("\n### Solution\n")
                out.append(sol_s + "\n")
    else:
        if sol:
            out.append("\n## Solution\n")
            out.append(sol + "\n")
    return "".join(out).rstrip() + "\n"

def strip_math_dollars(s: str) -> str:
    s = s.strip()
    if s.startswith("$$") and s.rstrip().endswith("$$"):
        return s[2 : len(s.rstrip()) - 2].strip()
    return s

def _normalize_formula_string(formula: str) -> str:
    """
    Normalizes a formula string to group duplicates:
    - remove outer $$ .. $$
    - collapse internal whitespace to single spaces
    """
    inner = strip_math_dollars(formula)
    inner = re.sub(r'\s+', ' ', inner.strip())
    return inner

def build_regex_from_formula(formula: str) -> re.Pattern:
    inner = _normalize_formula_string(formula)
    # token-wise \s+ between tokens to allow flexible spacing in solution
    tokens = inner.split(' ')
    esc_tokens = [re.escape(tok) for tok in tokens if tok != ""]
    inner_pattern = r"\s+".join(esc_tokens)
    full_pattern = r"\$\$\s*" + inner_pattern + r"\s*\$\$"
    return re.compile(full_pattern, flags=re.DOTALL)

def build_gs_groups(pv: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Group grading entries by normalized formula string.
    Returns: {norm_formula: {"pattern": compiled_regex, "indices": [idx1, idx2, ...]}}
    """
    groups: Dict[str, Dict[str, Any]] = {}
    for e in to_list(pv.get("grading_standard")):
        formula = e.get("formula")
        idx = e.get("index")
        if not (isinstance(formula, str) and (idx is not None)):
            continue
        norm = _normalize_formula_string(formula)
        try:
            pat = build_regex_from_formula(formula)
        except re.error:
            continue
        if norm not in groups:
            groups[norm] = {"pattern": pat, "indices": []}
        groups[norm]["indices"].append(idx)
    return groups

class SkipItem(Exception):
    """Signal that this item should be skipped entirely."""

def annotate_with_grading(md: str, groups: Dict[str, Dict[str, Any]]) -> Tuple[str, bool]:
    """
    Insert labels before each $$...$$ match, honoring duplicates:
    For each unique formula group, map the N-th occurrence in text to the N-th index.
    If any group's occurrences in text are fewer than required, return (md, False).
    """
    # Collect non-overlapping replacements: list of (start, end, replacement_text)
    replacements: List[Tuple[int, int, str]] = []

    for norm, info in groups.items():
        pat: re.Pattern = info["pattern"]
        indices: List[int] = info["indices"]

        # Find all occurrences in the markdown
        matches = list(pat.finditer(md))
        if len(matches) < len(indices):
            # Not enough occurrences to satisfy indices -> skip this item
            return md, False

        # Prepare replacements for the first len(indices) matches
        for occ_idx, idx_val in enumerate(indices):
            m = matches[occ_idx]
            before = f"\n&nbsp;&nbsp;&nbsp;&nbsp;**[formula {idx_val}]**: Dependent_Formula_Indices=[], Is_Final_Answer=[]\n"
            repl_text = before + remove_unit(m.group(0))
            replacements.append((m.start(), m.end(), repl_text))

    # Apply replacements in reverse order of start index to keep spans valid
    replacements.sort(key=lambda t: t[0], reverse=True)
    new_md = md
    for start, end, repl in replacements:
        new_md = new_md[:start] + repl + new_md[end:]
    return new_md, True

def render_QS_style(item: Dict[str, Any]) -> str:
    pv = extract_problem_view(item)
    md = render_QS_single_or_multi(pv)
    groups = build_gs_groups(pv)
    if groups:
        md2, ok = annotate_with_grading(md, groups)
        if not ok:
            raise SkipItem("Insufficient occurrences of a duplicated formula; skipping item.")
        md = md2
    md = remove_unit(md)
    return md

# ---------- I/O ----------

def write_outputs_for_item(item: Dict[str, Any], outdir_a: Path, outdir_b: Path) -> bool:
    """
    Returns True if files were written, False if item was skipped.
    """
    out_id = compute_output_id(item)
    if not out_id:
        raise ValueError("Cannot determine problem id (need 'problem.id' or 'problem_id'/'id').")

    try:
        a_md = render_A_style(item)
        b_md = render_QS_style(item)
    except SkipItem:
        # Skip both outputs for this item per requirement
        return False

    outdir_a.mkdir(parents=True, exist_ok=True)
    outdir_b.mkdir(parents=True, exist_ok=True)

    # A-style file
    (outdir_a / f"A{out_id}.md").write_text(a_md, encoding="utf-8")

    # Q-and-S-style file
    (outdir_b / f"QandS{out_id}.md").write_text(b_md, encoding="utf-8")
    return True

def main():
    parser = argparse.ArgumentParser(
        description="Convert problem JSON (flat or nested) into two MD outputs per problem."
    )
    parser.add_argument("--input_json", default="main_exp_deepseek_v3/01_compare.json",
                        help="Path to JSON file (list of items or single item).")
    parser.add_argument("--outdir_a", default="llm_response",
                        help='Dir for A-style files: "{outdir_a}/A{id}.md".')
    parser.add_argument("--outdir_b", default="problems_md",
                        help='Dir for Q&S-style files: "{outdir_b}/QandS{id}.md".')
    parser.add_argument("--sample_num", type=int, default=0)
    args = parser.parse_args()

    input_path = Path(args.input_json)
    if not input_path.exists():
        raise FileNotFoundError(f"Input JSON not found: {input_path}")

    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    items = to_list(data)
    items = [it for it in items if not has_duplicate_grades(it)]
    if args.sample_num > 0:
        items = random.sample(items, k=min(args.sample_num, len(items)))

    written = 0
    skipped = 0
    outdir_a = Path(args.outdir_a)
    outdir_b = Path(args.outdir_b)

    for item in items:
        if not isinstance(item, dict):
            continue
        ok = write_outputs_for_item(item, outdir_a, outdir_b)
        if ok:
            written += 1
        else:
            skipped += 1

    print(f"Done. Wrote {written} * 2 files to '{outdir_a}' and '{outdir_b}'. Skipped {skipped} items.")

if __name__ == "__main__":
    main()
