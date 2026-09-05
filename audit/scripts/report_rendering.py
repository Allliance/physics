"""TeX rendering adapted from the original PSet disagreement report."""

import re


def tex_escape(value: object) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "$": r"\$",
        "&": r"\&",
        "#": r"\#",
        "%": r"\%",
        "_": r"\_",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in str(value))


def verbatim(value: object, empty_message: str = "(No content supplied.)") -> str:
    text = str(value) if value is not None else ""
    if not text.strip():
        text = empty_message
    if r"\end{ReportText}" in text:
        raise ValueError("Report content contains the verbatim environment terminator")
    return "\\begin{ReportText}\n" + text.rstrip() + "\n\\end{ReportText}\n"


def normalize_stored_math(text: str) -> str:
    """Repair stored TeX wrappers and formulas that lack usable delimiters."""
    text = re.sub(
        r"(?m)^[ \t]*\\(?:documentclass\{[^}]+\}|"
        r"usepackage(?:\[[^]]*\])?\{[^}]+\}|"
        r"begin\{document\}|end\{document\})[ \t]*\n?",
        "",
        text,
    )
    text = re.sub(
        r"(Reference answer:\s*\n)(\\boxed\{.*\})\s*\Z",
        lambda match: match.group(1) + r"\[" + match.group(2) + r"\]",
        text,
        flags=re.S,
    )
    stripped = text.strip()
    if stripped.startswith(r"\displaystyle") and "\n" not in stripped:
        text = r"\[" + stripped + r"\]"
    text = text.replace(
        r"N + Mg \cos \theta = M a_\theta",
        r"\(N + Mg \cos \theta = M a_\theta\)",
    )
    return text


def render_plain_text(text: str) -> str:
    """Render non-math source text, including lightweight Markdown emphasis."""
    link_pattern = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
    rendered: list[str] = []
    position = 0
    for match in link_pattern.finditer(text):
        rendered.append(tex_escape(text[position : match.start()]))
        label = tex_escape(match.group(1))
        url = match.group(2).replace("%", r"\%").replace("#", r"\#")
        rendered.append(f"\\href{{{url}}}{{{label}}}")
        position = match.end()
    rendered.append(tex_escape(text[position:]))
    result = "".join(rendered)
    result = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", result)
    result = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\\emph{\1}", result)
    result = result.replace("---", "—")
    result = re.sub(r"\n[ \t]*\n+", r"\\par\\medskip\n", result)
    result = result.replace("\n", "\\par\n")
    return result


def find_closing_dollar(text: str, start: int, delimiter: str) -> int:
    position = start
    while True:
        position = text.find(delimiter, position)
        if position < 0:
            return -1
        backslashes = 0
        cursor = position - 1
        while cursor >= 0 and text[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            return position
        position += len(delimiter)


def render_math(delimiter: str, body: str) -> str:
    body = body.replace(r"\lt", "<")
    if delimiter in (r"\[", "$$"):
        stripped = body.strip()
        if re.fullmatch(r"\\begin\{align\*?\}.*\\end\{align\*?\}", stripped, re.S):
            return stripped
        return "\\[\n" + stripped + "\n\\]"
    return "\\(" + body.strip() + "\\)"


def rich_text(value: object, empty_message: str = "(No content supplied.)") -> str:
    """Compile stored TeX math while safely escaping surrounding prose."""
    text = str(value) if value is not None else ""
    if not text.strip():
        text = empty_message
    text = normalize_stored_math(text)
    rendered: list[str] = []
    plain_start = 0
    position = 0
    while position < len(text):
        delimiter = None
        closing = None
        if text.startswith("$$", position):
            delimiter, closing = "$$", "$$"
        elif text.startswith(r"\[", position):
            delimiter, closing = r"\[", r"\]"
        elif text.startswith(r"\(", position):
            delimiter, closing = r"\(", r"\)"
        elif text[position] == "$" and (position == 0 or text[position - 1] != "\\"):
            delimiter, closing = "$", "$"
        if delimiter is None:
            position += 1
            continue

        body_start = position + len(delimiter)
        if delimiter in ("$", "$$"):
            end = find_closing_dollar(text, body_start, closing)
        else:
            end = text.find(closing, body_start)
        if end < 0:
            position += len(delimiter)
            continue

        rendered.append(render_plain_text(text[plain_start:position]))
        rendered.append(render_math(delimiter, text[body_start:end]))
        position = end + len(closing)
        plain_start = position

    rendered.append(render_plain_text(text[plain_start:]))
    return "\\begin{ReportBody}\n" + "".join(rendered).strip() + "\n\\end{ReportBody}\n"


PREAMBLE = r"""\documentclass[10pt]{article}
\usepackage[a4paper,margin=18mm,headheight=15pt]{geometry}
\usepackage{fontspec}
\usepackage{microtype}
\usepackage[table]{xcolor}
\usepackage{booktabs}
\usepackage{tabularx}
\usepackage{longtable}
\usepackage{array}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{cancel}
\usepackage{fvextra}
\usepackage{fancyhdr}
\usepackage{titlesec}
\usepackage[hidelinks,unicode]{hyperref}

\setmainfont{DejaVu Sans}
\setsansfont{DejaVu Sans}
\setmonofont{DejaVu Sans Mono}
\renewcommand{\familydefault}{\sfdefault}
\setlength{\parindent}{0pt}
\setlength{\parskip}{5pt}
\setlength{\emergencystretch}{2em}
\allowdisplaybreaks
\definecolor{navy}{HTML}{18324A}
\definecolor{blue}{HTML}{2E628F}
\definecolor{pale}{HTML}{EEF4F8}
\definecolor{rulegray}{HTML}{AAB7C2}
\definecolor{textgray}{HTML}{425466}
\hypersetup{colorlinks=true,linkcolor=blue,urlcolor=blue}
\titleformat{\section}{\Large\bfseries\color{navy}}{}{0pt}{}
\titleformat{\subsection}{\large\bfseries\color{blue}}{}{0pt}{}
\titlespacing*{\section}{0pt}{16pt}{7pt}
\titlespacing*{\subsection}{0pt}{12pt}{4pt}
\pagestyle{fancy}
\fancyhf{}
\lhead{Physics Audits · Expert Review}
\rhead{\thepage}
\renewcommand{\headrulewidth}{0.3pt}
\DefineVerbatimEnvironment{ReportText}{Verbatim}{
  breaklines=true,
  breakanywhere=true,
  breakanywheresymbolpre={},
  breakanywheresymbolpost={},
  breaksymbolleft={},
  breaksymbolright={},
  fontsize=\small,
  frame=leftline,
  framerule=0.8pt,
  rulecolor=\color{rulegray},
  framesep=7pt,
  xleftmargin=9pt,
  tabsize=2
}
\newenvironment{ReportBody}{%
  \begin{list}{}{%
    \setlength{\leftmargin}{8pt}%
    \setlength{\rightmargin}{0pt}%
    \setlength{\topsep}{2pt}%
    \setlength{\partopsep}{0pt}%
  }\item\relax\small
}{\end{list}}
\newcommand{\meta}[2]{\textcolor{textgray}{\textbf{#1}} #2\quad}
\begin{document}
"""
