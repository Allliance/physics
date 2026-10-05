#!/usr/bin/env python3
# save_items_to_md.py
import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Union

def to_list(x: Union[List[Any], Any]) -> List[Any]:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]

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

def render_multi(item: Dict[str, Any]) -> str:
    """Render a multi-part problem with subquestions."""
    id_ = item.get("id", "")
    source = item.get("source", "")
    context = (item.get("context") or "").rstrip()
    images = to_list(item.get("images"))

    out = []
    title = f"# Problem {id_}" + (f" — {source}" if source else "")
    out.append(title)
    if context:
        out.append("\n## Context\n")
        out.append(context + "\n")
    img_block = render_images(images)
    if img_block:
        out.append(img_block)

    subqs = to_list(item.get("subquestions"))
    if subqs:
        for sq in subqs:
            letter = (sq.get("letter") or "").strip()
            header = f"## Subproblem ({letter})" if letter else "## Subproblem"
            out.append("\n" + header + "\n")
            prob_text = (sq.get("subproblem") or "").rstrip()
            if prob_text:
                out.append(prob_text + "\n")
            sol = (sq.get("solution") or "").rstrip()
            if sol:
                out.append("\n### Solution\n")
                out.append(sol + "\n")
    else:
        sol = (item.get("solution") or "").rstrip()
        if sol:
            out.append("\n## Solution\n")
            out.append(sol + "\n")

    return "".join(out).rstrip() + "\n"

def render_single(item: Dict[str, Any]) -> str:
    """Render a single-part problem (no subquestions key or empty)."""
    id_ = item.get("id", "")
    source = item.get("source", "")
    context = (item.get("context") or "").rstrip()
    images = to_list(item.get("images"))
    sol = (item.get("solution") or "").rstrip()

    out = []
    title = f"# Problem {id_}" + (f" — {source}" if source else "")
    out.append(title)
    if context:
        out.append("\n## Context\n")
        out.append(context + "\n")
    img_block = render_images(images)
    if img_block:
        out.append(img_block)
    if sol:
        out.append("\n## Solution\n")
        out.append(sol + "\n")
    return "".join(out).rstrip() + "\n"

def render_item(item: Dict[str, Any]) -> str:
    subqs = item.get("subquestions")
    if isinstance(subqs, list) and len(subqs) > 0:
        return render_multi(item)
    return render_single(item)

# ---------- Grading-standard tolerant matcher (new-line labels) ----------

def strip_math_dollars(s: str) -> str:
    """Remove surrounding $$ ... $$ if present; return inner text; else return original."""
    s = s.strip()
    if s.startswith("$$") and s.endswith("$"):
        # be permissive: treat trailing $$ even if there are spaces/newlines
        # Find first $$ and last $$ safely
        if s.startswith("$$") and s.rstrip().endswith("$$"):
            core = s[2:len(s) - 2]
            return core.strip()
    return s

def build_regex_from_formula(formula: str) -> re.Pattern:
    """
    Build a regex that matches the GS formula inside $$ ... $$ with flexible whitespace.
    Will match forms like:
        $$\n<inner with varying spaces>\n$$
    """
    inner = strip_math_dollars(formula)

    # Tokenize on whitespace; re-escape tokens literally; join with \s+
    tokens = re.split(r'\s+', inner.strip())
    esc_tokens = [re.escape(tok) for tok in tokens if tok != ""]
    inner_pattern = r"\s+".join(esc_tokens)

    # Full display-math block with optional whitespace around inner
    full_pattern = r"\$\$\s*" + inner_pattern + r"\s*\$\$"

    return re.compile(full_pattern, flags=re.DOTALL)

def build_gs_entries(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries = []
    for e in to_list(item.get("grading_standard")):
        formula = e.get("formula")
        idx = e.get("index")
        if isinstance(formula, str) and idx is not None:
            try:
                pat = build_regex_from_formula(formula)
                entries.append({"pattern": pat, "index": idx})
            except re.error:
                continue
    return entries

def annotate_with_grading(md: str, entries: List[Dict[str, Any]]) -> str:
    """
    After each matched $$...$$ block, insert a new line '(formula <index>)'.
    Avoid double labeling if the very next non-empty line is already '(formula <number>)'.
    """
    # We'll rebuild the text iteratively to make following-context checks robust.
    for e in entries:
        pat = e["pattern"]
        idx = e["index"]

        def repl(m: re.Match) -> str:
            matched = m.group(0)
            # Look ahead at immediate following text
            tail = md[m.end(): m.end() + 64]  # small window
            # If next non-empty line already starts with (formula X), skip
            # Allow optional whitespace and a newline
            if re.match(r'^[ \t]*\r?\n[ \t]*\((?i:formula)\s+\d+\)', tail):
                return matched
            # Otherwise, add newline + label
            
            matched = remove_unit(matched)
            return f"\n&nbsp;&nbsp;&nbsp;&nbsp;**[formula {idx}]**: Dependent_Formula_Indices=[], Is_Final_Answer=[]\n" + matched

        md = pat.sub(repl, md)
    return md

def remove_unit(s: str) -> str:
    return re.sub(r'\\unit\{([^}]*)\}', r'\1', s)
# ---------- I/O ----------

def write_markdown(item: Dict[str, Any], outdir: Path) -> None:
    if "id" not in item:
        raise ValueError("Each item must have an 'id' field.")
    outdir.mkdir(parents=True, exist_ok=True)
    filename = outdir / f"QandS{item['id']}.md"

    md = render_item(item)
    gs_entries = build_gs_entries(item)
    if gs_entries:
        md = annotate_with_grading(md, gs_entries)
    md = remove_unit(md)
    filename.write_text(md, encoding="utf-8")

def main():
    parser = argparse.ArgumentParser(
        description="Convert problem JSON items to per-id Markdown files (problems + solutions only)."
    )
    parser.add_argument("--input_json",default="dag.json", help="Path to JSON file (list of items or single item).")
    parser.add_argument(
        "--outdir",
        default="problems_md",
        help='Output folder. Files will be written as "{outdir}/{id}.md".'
    )
    args = parser.parse_args()

    input_path = Path(args.input_json)
    outdir = Path(args.outdir)

    if not input_path.exists():
        raise FileNotFoundError(f"Input JSON not found: {input_path}")

    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    items = to_list(data)
    for item in items:
        if not isinstance(item, dict):
            continue
        write_markdown(item, outdir)

    print(f"Done. Wrote {len(items)} file(s) to {outdir}")

if __name__ == "__main__":
    main()
