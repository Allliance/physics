#!/usr/bin/env python3
# merge_md_sets.py
import argparse
import re
from pathlib import Path
from typing import List, Tuple

TITLE_RE = re.compile(r'^(#\s*Problem\s+)([^\s#\n]+)(.*)$', flags=re.MULTILINE)

def set_tags(n1: int, n2: int) -> List[str]:
    return [f"{i:02d}" for i in range(n1, n2 + 1)]

def list_md_files(dir_path: Path, prefix: str) -> List[Path]:
    if not dir_path.exists():
        return []
    return sorted(dir_path.glob(f"{prefix}*.md"))

def extract_id_from_filename(p: Path, prefix: str) -> str:
    # e.g., A1001.md -> 1001 ; QandS1001.md -> 1001
    name = p.stem
    assert name.startswith(prefix), f"Unexpected filename: {p.name}"
    return name[len(prefix):]

def rewrite_title_with_set(content: str, set_tag: str, new_id: str) -> str:
    """
    Replace the FIRST '# Problem <id>' with '# Problem <set>-<id>'.
    We only rewrite the first match to avoid touching references/examples.
    """
    def _repl(m: re.Match) -> str:
        return f"{m.group(1)}{set_tag}-{new_id}{m.group(3)}"
    # Only substitute the first match
    return TITLE_RE.sub(_repl, content, count=1)

def merge_group(
    base: Path,
    set_list: List[str],
    file_prefix: str,          # "A" or "QandS"
    out_file: Path,
) -> int:
    merged_chunks: List[Tuple[str, str]] = []  # (sort_key, content)
    for tag in set_list:
        folder = base / tag
        files = list_md_files(folder, file_prefix)
        for p in files:
            orig_id = extract_id_from_filename(p, file_prefix)
            text = p.read_text(encoding="utf-8")
            text2 = rewrite_title_with_set(text, tag, orig_id)

            # sort key: by set tag then by orig_id (string sort; tweak if you want numeric)
            sort_key = f"{tag}-{orig_id}"
            # add a separator for readability
            block = f"\n\n---\n\n<!-- {file_prefix}{orig_id} from set {tag} -->\n\n{text2.strip()}\n"
            merged_chunks.append((sort_key, block))

    merged_chunks.sort(key=lambda x: x[0])
    out_file.parent.mkdir(parents=True, exist_ok=True)
    header = f"# Merged {'LLM Responses' if file_prefix=='A' else 'Problems'}\n\n"
    out_text = header + "".join([b for _, b in merged_chunks]).lstrip()
    out_file.write_text(out_text, encoding="utf-8")
    return len(merged_chunks)

def main():
    ap = argparse.ArgumentParser(description="Merge A*.md and QandS*.md across sets and prefix IDs with set tag.")
    ap.add_argument("--base", default="main_exp_deepseek_v3", help="Base directory containing 01..07 folders.")
    ap.add_argument("--start", type=int, default=1, help="Start set number (default: 1)")
    ap.add_argument("--end", type=int, default=7, help="End set number (default: 7)")
    ap.add_argument("--out_llm", default="all_sampled_responses.md", help="Output filename for merged A*.md")
    ap.add_argument("--out_problems", default="all_sampled_problems.md", help="Output filename for merged QandS*.md")
    args = ap.parse_args()

    base = Path(args.base)
    sets = set_tags(args.start, args.end)

    llm_out = base / args.out_llm
    prob_out = base / args.out_problems

    n_llm = merge_group(base, sets, "A", llm_out)
    n_prob = merge_group(base, sets, "QandS", prob_out)

    print(f"Merged {n_llm} LLM response files into {llm_out}")
    print(f"Merged {n_prob} problem files into {prob_out}")

if __name__ == "__main__":
    main()
