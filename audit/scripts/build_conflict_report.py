#!/usr/bin/env python3
"""Build an expert-review PDF containing only unresolved audit conflicts."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

from report_rendering import PREAMBLE, rich_text, tex_escape, verbatim


AUDIT_DIR = Path(__file__).resolve().parents[1]


def load_conflicts(conflicts_path: Path, selected_dir: Path) -> list[dict]:
    payload = json.loads(conflicts_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("conflicts"), list):
        raise ValueError("Expected a conflicts.json object containing a conflicts list")
    entries = {}
    for conflict in payload["conflicts"]:
        if conflict.get("status") == "resolved":
            continue
        if conflict.get("status") != "unresolved":
            raise ValueError(f"Unknown conflict status: {conflict.get('status')!r}")
        key = (conflict["dataset"], conflict["source_problem_id"])
        if key in entries:
            raise ValueError(f"Duplicate conflict for {key}")
        audits = conflict.get("audits")
        if not isinstance(audits, list) or not audits:
            raise ValueError(f"No audit passes for {key}")
        for audit in audits:
            if (audit["dataset"], audit["source_problem_id"]) != key:
                raise ValueError(f"Audit identity does not match conflict {key}")
            if str(audit["display_id"]) != str(conflict["display_id"]):
                raise ValueError(f"Audit display ID does not match conflict {key}")
        entries[key] = dict(conflict, audits=sorted(audits, key=lambda audit: int(audit["pass"])))

    datasets = {key[0] for key in entries}
    for path in sorted(selected_dir.glob("*/responses.jsonl")):
        if path.parent.name not in datasets:
            continue
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                response = json.loads(line)
                key = (path.parent.name, str(response["problem_id"]))
                if key not in entries:
                    continue
                entry = entries[key]
                if "response" in entry:
                    raise ValueError(f"Duplicate selected response for {key}")
                if "display_id" in response and str(response["display_id"]) != str(entry["display_id"]):
                    raise ValueError(f"Selected response display ID mismatch for {key}")
                for field in ("problem_statement", "reference_solution", "model_response"):
                    if not isinstance(response.get(field), str):
                        raise ValueError(f"Missing or non-text {field} for {key}")
                entry["response"] = response
                entry["response_source"] = {"path": str(path.resolve()), "line": line_number}
    missing = [key for key, entry in entries.items() if "response" not in entry]
    if missing:
        raise ValueError(f"Missing selected responses: {missing}")
    return sorted(entries.values(), key=lambda entry: (
        int(entry["display_id"]), entry["dataset"], entry["source_problem_id"],
    ))


def build_tex(entries: list[dict], conflicts_path: Path, literal_blocks: set[str] | None = None) -> str:
    def render(block, value, empty_message="(No content supplied.)"):
        body = verbatim(value, empty_message) if block in (literal_blocks or set()) else rich_text(value, empty_message)
        return f"% report-block: {block}\n{body}% report-block-end\n"

    parts = [PREAMBLE, r"""
\setcounter{tocdepth}{1}
\setcounter{secnumdepth}{0}
\begin{titlepage}
\vspace*{28mm}
{\Huge\bfseries\color{navy} Physics Audit\\[3mm]Expert Review Dossier\par}
\vspace{8mm}
""", f"{{\\Large {len(entries)} unresolved problems for expert review\\par}}\n", r"""
\vspace{15mm}
\colorbox{pale}{\parbox{0.91\textwidth}{\vspace{3mm}
\textbf{Review task.} For each problem, choose a final label and provide a short
explanation. All available human audit passes are preserved. No final label has
been assigned to these conflicts. Problems already resolved by overrides are excluded.
\vspace{3mm}}}
\vfill
""", tex_escape(date.today().isoformat()), r"""
\end{titlepage}
\section*{Report guide}
Each problem contains the complete stored question, reference solution, model
response, all human audits, and the stored AI audit when available. Mathematics
is typeset for reading. The accompanying JSON preserves the original text and
maps the report's question numbers to dataset and source problem IDs.

\textbf{Final labels:} \texttt{PROBLEM\_FAILURE},
\texttt{GRADER\_FAILURE}, or \texttt{MODEL\_FAILURE}.
Stored AI verdicts use their original taxonomy; they are not final expert decisions.

\section*{Review overview}
\begingroup\small
\begin{longtable}{p{9mm}p{13mm}p{24mm}p{106mm}}
\toprule
\textbf{Q} & \textbf{ID} & \textbf{Benchmark} & \textbf{Human labels by pass}\\
\midrule\endhead
"""]
    for number, entry in enumerate(entries, start=1):
        labels = "; ".join(f"{audit['pass']}: {audit['label']}" for audit in entry["audits"])
        parts.append(f"{number} & {tex_escape(entry['display_id'])} & "
                     f"{tex_escape(entry['dataset'])} & {tex_escape(labels)} \\\\\n")
    parts.append(r"""\bottomrule
\end{longtable}\endgroup
\tableofcontents
\clearpage
""")
    for number, entry in enumerate(entries, start=1):
        response = entry["response"]
        parts.extend([
            f"\\section{{Q{number}: Display ID {tex_escape(entry['display_id'])}}}\n",
            f"\\meta{{Benchmark:}}{{{tex_escape(entry['dataset'])}}}\n",
            f"\\meta{{Source problem ID:}}{{{tex_escape(entry['source_problem_id'])}}}\\par\n",
            f"\\meta{{Category:}}{{{tex_escape(entry['audits'][0].get('category', ''))}}}\\par\n",
            render(f"Q{number}-reason", entry.get("reason", "Human audit labels disagree.")),
        ])
        for heading, field in [("Question", "problem_statement"), ("Reference solution", "reference_solution"),
                               ("AI solution", "model_response")]:
            parts.extend([f"\\subsection{{{heading}}}\n", render(f"Q{number}-{field}", response[field])])
        for audit in entry["audits"]:
            parts.extend([
                f"\\subsection{{Human auditor — pass {tex_escape(audit['pass'])}}}\n",
                f"\\meta{{Annotation ID:}}{{{tex_escape(audit['annotation_id'])}}}\\par\n",
                f"\\meta{{Label:}}{{\\texttt{{{tex_escape(audit['label'])}}}}}\\par\n",
                render(f"Q{number}-pass{audit['pass']}", audit["note"], "(No note supplied by this auditor.)"),
            ])
        ai_audit = response.get("AI_audit") or {}
        parts.extend([
            "\\subsection{AI audit}\n",
            f"\\meta{{Verdict:}}{{{tex_escape(ai_audit.get('verdict', '(not supplied)'))}}}\\par\n",
            f"\\meta{{Category:}}{{{tex_escape(ai_audit.get('category', '(not supplied)'))}}}\\par\n",
            render(f"Q{number}-AI_audit", ai_audit.get("reason"), "(No AI-audit rationale supplied.)"),
            "\\subsection{Stored scoring metadata}\n",
            f"\\meta{{Original score:}}{{{tex_escape(response.get('original_score', '(not supplied)'))}}}\n",
            f"\\meta{{Rule-based binary score:}}{{{tex_escape(response.get('rule_based_binary_score', '(not supplied)'))}}}\\par\n",
            "\\subsection{Expert decision}\n",
            "Final label: \\hrulefill\\par\nNotes: \\hrulefill\\par\\vspace{8mm}\\hrule\\vspace{8mm}\\hrule\n",
            "\\clearpage\n",
        ])
    parts.extend([
        "\\section*{Provenance}\n\\addcontentsline{toc}{section}{Provenance}\n",
        "\\textbf{Conflict source}\\par\n", verbatim(str(conflicts_path.resolve())),
        "\\textbf{Selected response records}\\par\n",
    ])
    for number, entry in enumerate(entries, start=1):
        source = entry["response_source"]
        parts.append(verbatim(f"Q{number}: {source['path']} (JSONL line {source['line']})"))
    parts.append("\\end{document}\n")
    return "".join(parts)


class LatexError(ValueError):
    def __init__(self, output: str):
        super().__init__("xelatex failed:\n" + "\n".join(output.splitlines()[-60:]))
        match = re.search(r"(?m)^l\.(\d+)\s", output)
        self.line_number = int(match.group(1)) if match else None


def failed_block(tex: str, line_number: int | None) -> str | None:
    if line_number is None:
        return None
    block = None
    for line in tex.splitlines()[:line_number]:
        if line.startswith("% report-block: "):
            block = line.removeprefix("% report-block: ")
        elif line == "% report-block-end":
            block = None
    return block


def compile_pdf(tex: str, directory: Path) -> Path:
    if not shutil.which("xelatex"):
        raise ValueError("xelatex is required; install TeX Live with XeLaTeX (see audit/README.md)")
    (directory / "report.tex").write_text(tex, encoding="utf-8")
    # A third pass accounts for the space occupied by the populated contents page.
    for _ in range(3):
        result = subprocess.run(
            ["xelatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "report.tex"],
            cwd=directory, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120,
        )
        if result.returncode:
            raise LatexError(result.stdout)
    return directory / "report.pdf"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conflicts", type=Path, default=AUDIT_DIR / "conflicts.json")
    parser.add_argument("--selected-dir", type=Path, default=AUDIT_DIR / "selected")
    parser.add_argument("--output", type=Path, default=AUDIT_DIR / "reports" / "unresolved_conflicts.pdf")
    args = parser.parse_args()
    if args.output.suffix.lower() != ".pdf":
        parser.error("--output must have a .pdf extension")
    if args.conflicts.resolve() in {args.output.with_suffix(suffix).resolve() for suffix in (".pdf", ".tex", ".json")}:
        parser.error("Report outputs must not overwrite the input conflicts file")
    try:
        entries = load_conflicts(args.conflicts, args.selected_dir)
        literal_blocks = set()
        payload = {
            "generated_on": date.today().isoformat(),
            "conflicts_source": str(args.conflicts.resolve()),
            "problem_count": len(entries),
            "problems": [dict(entry, question_number=number) for number, entry in enumerate(entries, start=1)],
        }
        # Compile in isolation; failed builds leave previously generated reports intact.
        with tempfile.TemporaryDirectory(prefix="audit-report-") as directory:
            while True:
                tex = build_tex(entries, args.conflicts, literal_blocks)
                try:
                    pdf = compile_pdf(tex, Path(directory))
                    break
                except LatexError as error:
                    block = failed_block(tex, error.line_number)
                    if block is None or block in literal_blocks:
                        raise
                    literal_blocks.add(block)
                    print(f"Stored math could not compile in {block}; preserving this section as source text.", flush=True)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(pdf, args.output)
        payload["source_text_sections"] = sorted(literal_blocks)
        args.output.with_suffix(".tex").write_text(tex, encoding="utf-8")
        args.output.with_suffix(".json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (ValueError, KeyError, OSError, subprocess.TimeoutExpired) as error:
        parser.error(str(error))
    print(f"Wrote {args.output} ({len(entries)} unresolved problems)")
    print(f"Report source and question mapping: {args.output.with_suffix('.tex')}, {args.output.with_suffix('.json')}")


if __name__ == "__main__":
    main()
