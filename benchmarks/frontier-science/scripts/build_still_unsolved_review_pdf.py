#!/usr/bin/env python3
"""Build a typeset PDF review of the still-unsolved FrontierScience questions."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "artifacts/gpt-5.6-sol-high-tools-on-five-round-failures/still_unsolved_questions_with_all_answers.jsonl"
DEFAULT_OUTPUT = DEFAULT_INPUT.with_name("still_unsolved_questions_review.pdf")


def normalize_markdown(value: object) -> str:
    """Undo dataset escaping and expose TeX math to Pandoc."""
    text = str(value or "").replace("\r\n", "\n").replace("\x00", "")
    linebreaks: list[str] = []
    def protect_linebreak(match: re.Match[str]) -> str:
        linebreaks.append(match.group(0))
        return f"@@TEXLINEBREAK{len(linebreaks) - 1}@@"
    text = re.sub(r"\\\\\[[0-9.]+(?:mm|cm|pt|em|ex)\]", protect_linebreak, text)
    # Some source fields preserve an extra JSON-era slash before every TeX command.
    text = re.sub(r"\\\\(?=[A-Za-z,;!\[\]\(\)])", r"\\", text)
    for escaped, delimiter in ((r"\\(", r"\("), (r"\\)", r"\)"),
                               (r"\\[", r"\["), (r"\\]", r"\]")):
        text = text.replace(escaped, delimiter)
    text = re.sub(r"`\s*(\\\(.*?\\\))\s*`", r"\1", text, flags=re.S)
    text = re.sub(r"`\s*(\\\[.*?\\\])\s*`", r"\1", text, flags=re.S)
    text = re.sub(r"`\s*(\$\$.*?\$\$)\s*`", r"\1", text, flags=re.S)
    # Repair occasional line-local mismatched delimiters without confusing escaped
    # interval brackets such as \[0, 2\pi\).
    repaired_lines = []
    for line in text.splitlines():
        if r"\(" in line and r"\)" not in line and line.rstrip().endswith(r"\]"):
            line = line.rstrip()[:-2] + r"\)"
        elif r"\[" in line and r"\]" not in line and line.rstrip().endswith(r"\)"):
            line = line.rstrip()[:-2] + r"\]"
        while line.count(r"\(") > line.count(r"\)"):
            start = line.rfind(r"\(")
            bracket = line.find("]", start + 2)
            if bracket != -1:
                replace_start = bracket - 1 if line[bracket - 1:bracket] == "\\" else bracket
                line = line[:replace_start] + r"\)" + line[bracket + 1:]
            else:
                line += r"\)"
        repaired_lines.append(line)
    text = "\n".join(repaired_lines)
    for index, linebreak in enumerate(linebreaks):
        text = text.replace(f"@@TEXLINEBREAK{index}@@", linebreak)
    substitutions = {
        "−": "-", "µ": r"\(\mu\)", "μ": r"\(\mu\)", "ω": r"\(\omega\)",
        "α": r"\(\alpha\)", "β": r"\(\beta\)", "γ": r"\(\gamma\)",
        "δ": r"\(\delta\)", "ε": r"\(\epsilon\)", "θ": r"\(\theta\)",
        "λ": r"\(\lambda\)", "π": r"\(\pi\)", "σ": r"\(\sigma\)",
        "τ": r"\(\tau\)", "φ": r"\(\phi\)", "χ": r"\(\chi\)",
        "ψ": r"\(\psi\)", "Δ": r"\(\Delta\)", "Γ": r"\(\Gamma\)",
        "Φ": r"\(\Phi\)", "Ψ": r"\(\Psi\)", "Σ": r"\(\Sigma\)",
        "Θ": r"\(\Theta\)", "∞": r"\(\infty\)", "±": r"\(\pm\)",
        "×": r"\(\times\)", "√": r"\(\sqrt{}\)", "∂": r"\(\partial\)",
        "∫": r"\(\int\)", "⊗": r"\(\otimes\)", "⊙": r"\(\odot\)",
        "⟨": r"\(\langle\)", "⟩": r"\(\rangle\)", "→": r"\(\to\)",
        "≥": r"\(\ge\)", "≫": r"\(\gg\)", "≈": r"\(\approx\)",
        "≃": r"\(\simeq\)", "²": r"\(^2\)", "₀": r"\(_0\)",
        "₁": r"\(_1\)", "₂": r"\(_2\)", "′": "'", "″": "''",
        "ṙ": r"\(\dot r\)", "Ṡ": r"\(\dot S\)", "☉": r"\(\odot\)",
        "★": r"\(\star\)", "†": r"\(\dagger\)",
    }
    math_commands = {
        symbol: (replacement[2:-2] if replacement.startswith(r"\(") and replacement.endswith(r"\)") else replacement)
        for symbol, replacement in substitutions.items()
    }
    environments: list[str] = []
    def protect_environment(match: re.Match[str]) -> str:
        environment = match.group(0).translate(str.maketrans(math_commands))
        environment = environment.replace(r"\(", "").replace(r"\)", "")
        environment = environment.replace(r"\[", "[").replace(r"\]", "]")
        environment = environment.replace(r"\_", "_").replace(r"\&", "&")
        environments.append(environment)
        return f"@@TEXENVIRONMENT{len(environments) - 1}@@"
    text = re.sub(
        r"\\begin\{(align\*?|equation\*?|gather\*?|multline\*?)\}.*?\\end\{\1\}",
        protect_environment, text, flags=re.S,
    )
    math_pattern = re.compile(r"(\\\(.*?\\\)|\\\[.*?\\\]|\$\$.*?\$\$|\$(?!\$).*?\$)", re.S)
    bare_symbol = re.compile(
        r"\\(alpha|beta|gamma|delta|epsilon|theta|lambda|mu|pi|sigma|tau|phi|chi|psi|omega|"
        r"Gamma|Delta|Theta|Sigma|Phi|Psi|infty|pm|odot|otimes|dagger|star)\b"
    )
    def outside_math(fragment: str) -> str:
        wrapped = bare_symbol.sub(lambda match: r"\(" + match.group(0) + r"\)", fragment)
        return wrapped.translate(str.maketrans(substitutions))
    pieces = []
    cursor = 0
    for match in math_pattern.finditer(text):
        pieces.append(outside_math(text[cursor:match.start()]))
        math = match.group(0).translate(str.maketrans(math_commands))
        if math.startswith(r"\("):
            body = re.sub(r"(?<!\\)\\\[", "[", math[2:-2])
            body = re.sub(r"(?<!\\)\\\]", "]", body)
            math = math[:2] + body + math[-2:]
        if not re.search(r"\\begin\{(?:align|aligned|array|matrix|cases|split)", math):
            math = math.replace("&", r"\&")
        else:
            math = math.replace(r"\&", "&")
        pieces.append(math)
        cursor = match.end()
    pieces.append(outside_math(text[cursor:]))
    result = "".join(pieces)
    result = re.sub(r"\\\)\s*\\\(", " ", result)
    result = re.sub(r"\\\((.*?)\\\)([0-9])", lambda m: r"\(" + m.group(1) + " " + m.group(2) + r"\)", result)
    for command in ("big", "Big", "bigg", "Bigg", "left", "right"):
        result = result.replace(rf"\{command}\[", rf"\{command}[")
        result = result.replace(rf"\{command}\]", rf"\{command}]")
    for index, environment in enumerate(environments):
        result = result.replace(f"@@TEXENVIRONMENT{index}@@", environment)
    return result


def build_markdown(rows: list[dict]) -> str:
    parts = [
        "---\n",
        'title: "FrontierScience Physics: Still-Unsolved Review"\n',
        'subtitle: "GPT-5.6 Sol · High Reasoning · Tools Enabled"\n',
        'date: "17 questions: 10 Olympiad, 7 Research/PhD"\n',
        "toc: true\ntoc-depth: 1\ngeometry: margin=0.68in\nfontsize: 10pt\n",
        "colorlinks: true\nlinkcolor: MidnightBlue\n---\n\n",
        "This report contains each complete problem, the latest tool-enabled model response, "
        "and the judge's score and feedback.\n\n",
    ]
    for index, row in enumerate(rows, start=1):
        attempt = row["tool_enabled_attempt"]
        tools = ", ".join(attempt["tool_types"]) if attempt["tool_types"] else "none used"
        parts.extend([
            "\\newpage\n\n", f"# {index}. {row['track'].title()} problem\n\n",
            f"**ID:** `{row['id']}`  \n**Tool-enabled score:** {attempt['score']}  \n",
            f"**Tool use:** {tools} ({attempt['tool_call_count']} calls)\n\n",
            "## Question\n\n", normalize_markdown(row["problem"]), "\n\n",
            "## GPT-5.6 Sol response (high reasoning, tools available)\n\n",
            normalize_markdown(attempt["response"]), "\n\n",
            "## Judge feedback\n\n", normalize_markdown(attempt["judge_reasoning"]), "\n\n",
        ])
    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    dependency_dir = Path("/tmp/frontier_pdf_deps")
    if dependency_dir.is_dir():
        sys.path.insert(0, str(dependency_dir))
    import pypandoc
    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    build_dir = args.output.parent / ".pdf-build"
    build_dir.mkdir(exist_ok=True)
    markdown_path = build_dir / "still_unsolved_questions_review.md"
    markdown_path.write_text(build_markdown(rows), encoding="utf-8")
    header_path = build_dir / "physics_header.tex"
    header_path.write_text("\\usepackage{braket}\n", encoding="utf-8")
    pypandoc.convert_file(
        str(markdown_path), "pdf", outputfile=str(args.output),
        format="markdown+tex_math_single_backslash+tex_math_dollars+raw_tex",
        extra_args=["--pdf-engine=pdflatex", "--standalone", "--number-sections",
                    f"--include-in-header={header_path}"],
    )
    print(f"Wrote {args.output} ({len(rows)} questions, typeset mathematics)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
