"""Convert the bundled expert solution to TeX after checking the example website."""

import html
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "benchmarks/critpt/data/example_challenges/quantum_error_correction.ipynb"
PAGE = ROOT / "scratch/critpt_example.html"
OUTPUT = ROOT / "analysis/CritPt/solutions/00"


def normalize(text):
    return re.sub(r"\s+", "", text).replace("$", "")


def math_block(match):
    content = match.group(1).strip()
    content = content.replace(r"\begin{align}", r"\begin{aligned}")
    content = content.replace(r"\end{align}", r"\end{aligned}")
    return "\n\\[\n\\fitmath{" + content + "}\n\\]\n"


def main():
    notebook = json.loads(SOURCE.read_text())
    solution = "".join(notebook["cells"][27]["source"])
    code = "".join(notebook["cells"][28]["source"])
    page = PAGE.read_text()
    expert = page.split('<div class="expert-solution-container">', 1)[1].split("</code></pre>", 1)[0] + "</code></pre>"
    paragraphs = [html.unescape(re.sub(r"<[^>]+>", "\n", body))
                  for body in re.findall(r"<p\b[^>]*>(.*?)</p>", expert, re.S)]
    narrative = re.sub(r"^#+[^\n]*", "", solution, flags=re.M)
    assert normalize(narrative) == normalize("\n".join(paragraphs))
    web_code = html.unescape(re.search(r"<code[^>]*>(.*?)</code>", expert, re.S).group(1))
    assert code.splitlines() == web_code.splitlines()
    answer = html.unescape(re.search(r'<div class="answer-box">(.*?)</div>', page, re.S).group(1)).strip().strip("$")
    local_answer = "".join(notebook["cells"][5]["source"]).split("\n", 1)[1]
    assert normalize(answer.replace(r"\tfrac", r"\frac")) == normalize(local_answer)

    preamble = r"""% Challenge 0: Quantum Error Detection, CritPt official example.
% Source: https://critpt.com/example.html (verified 2026-09-06).
% Converted from the supplied quantum_error_correction.ipynb, whose expert
% narrative and enumeration code match the website (formatting normalized).
% Original wording and mathematical content are preserved.
\documentclass[10pt]{article}
\usepackage[a4paper,margin=18mm]{geometry}
\usepackage[T1]{fontenc}
\usepackage{amsmath,amssymb,graphicx,url,listings}
\newsavebox{\equationbox}
\newcommand{\fitmath}[1]{%
  \sbox{\equationbox}{$\displaystyle #1$}%
  \ifdim\wd\equationbox>\linewidth
    \resizebox{\linewidth}{!}{\usebox{\equationbox}}%
  \else\usebox{\equationbox}\fi}
\lstset{language=Python,basicstyle=\scriptsize\ttfamily,breaklines=true,
  columns=fullflexible,keepspaces=true,showstringspaces=false}
\begin{document}
"""
    source_line = "\nSource: \\url{https://critpt.com/example.html}.\n\n"
    answer_tex = preamble + "\\section*{Challenge 00: Final answer}\n" + source_line
    answer_tex += "For the post-selected logical state in the designated challenge:\n"
    answer_tex += "\\[\n\\fitmath{" + answer + "}\n\\]\n\\end{document}\n"

    solution = re.sub(r"^# Detailed solution:\s*", "", solution)
    solution = re.sub(r"^### For subproblem ([123])", lambda m: r"\subsection*{Checkpoint " + m[1] + "}", solution, flags=re.M)
    solution = solution.replace("*logical*", r"\emph{logical}")
    solution = re.sub(r"\$\$(.*?)\$\$", math_block, solution, flags=re.S)
    solution_tex = preamble + "\\section*{Challenge 00: Detailed expert solution}\n" + source_line
    solution_tex += solution.rstrip() + "\n\n\\subsection*{Enumeration code}\n\\begin{lstlisting}\n"
    solution_tex += code.rstrip() + "\n\\end{lstlisting}\n\\end{document}\n"

    OUTPUT.mkdir(parents=True, exist_ok=True)
    destination = OUTPUT / "supporting" if (OUTPUT / "supporting").exists() else OUTPUT
    (destination / "final_answer.tex").write_text(answer_tex)
    (destination / "detailed_solution.tex").write_text(solution_tex)
    if destination != OUTPUT:
        from normalize_solution_roles import normalize_roles
        normalize_roles(OUTPUT.parent)
    print("Verified the designated answer, full expert narrative, and enumeration code against the website.")
    print("Saved final_answer.tex and detailed_solution.tex in", OUTPUT)


if __name__ == "__main__":
    main()
