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
    response = item.get("response", "")
    # print(response)
    title = f"# Problem {id_}"
    return f"{title}\n\n{response.strip()}\n"

def render_item(item: Dict[str, Any]) -> str:
    # subqs = item.get("subquestions")
    # if isinstance(subqs, list) and len(subqs) > 0:
    #     return render_multi(item)
    return render_single(item)

def remove_unit(s: str) -> str:
    return re.sub(r'\\unit\{([^}]*)\}', r'\1', s)
# ---------- I/O ----------

def add_score_placeholder(s: str) -> str:
    return s + "\n\n## Scoring\n**Score (100 pts max)**: 50% score=[], 16% score = [], 84% score = [].\n(16% score <= 50% score <= 84% score)\n\n(Note that for normal distribution, mean, mean-std, mean+std corresponds to 50% score, 16% score and 84% score).\n"

def write_markdown(item: Dict[str, Any], outdir: Path) -> None:
    item['id'] = item['problem_id']
    if "id" not in item:
        raise ValueError("Each item must have an 'id' field.")
    outdir.mkdir(parents=True, exist_ok=True)
    filename = outdir / f"A{item['id']}.md"

    md = render_item(item)
    md = remove_unit(md)
    md = add_score_placeholder(md)
    filename.write_text(md, encoding="utf-8")

def main():
    parser = argparse.ArgumentParser(
        description="Convert problem JSON items to per-id Markdown files (problems + solutions only)."
    )
    parser.add_argument("--input_json",default="llm_answer.json", help="Path to JSON file (list of items or single item).")
    parser.add_argument(
        "--outdir",
        default="llm_response",
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
