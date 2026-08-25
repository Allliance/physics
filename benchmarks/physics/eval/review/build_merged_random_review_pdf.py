#!/usr/bin/env python3
# /// script
# dependencies = ["weasyprint>=69"]
# ///
"""Render the merged random review set as a physicist-readable PDF."""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from weasyprint import HTML


ROOT = Path(__file__).resolve().parents[2]
REVIEW_DIR = Path(__file__).resolve().parent


class MathRenderer:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, tex: str, *, display: bool) -> str:
        index = len(self.items)
        self.items.append({"tex": tex.strip(), "display": display})
        return f"@@MATH_{index}@@"

    def render_all(self) -> list[str]:
        if not self.items:
            return []
        script = r"""
const fs = require("fs");
const katex = require("./inspection/static/vendor/katex/katex.min.js");
const items = JSON.parse(fs.readFileSync(0, "utf8"));
const rendered = items.map((item) => katex.renderToString(item.tex, {
  displayMode: item.display,
  throwOnError: false,
  strict: false,
}));
process.stdout.write(JSON.stringify(rendered));
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            input=json.dumps(self.items),
            text=True,
            check=True,
            capture_output=True,
        )
        return json.loads(result.stdout)


def normalize_escaped_latex(value: str) -> str:
    return (
        value
        .replace(r"\\[", r"\[")
        .replace(r"\\]", r"\]")
        .replace(r"\\(", r"\(")
        .replace(r"\\)", r"\)")
        .replace(r"\\{", r"\{")
        .replace(r"\\}", r"\}")
    )


def normalize_source_latex(value: Any) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\\\\([A-Za-z])", r"\\\1", text)
    return normalize_escaped_latex(text)


def is_unescaped_dollar(text: str, index: int) -> bool:
    if text[index] != "$":
        return False
    slashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        slashes += 1
        cursor -= 1
    return slashes % 2 == 0


def find_next_delimiter(text: str, start: int) -> tuple[int, str, str, bool] | None:
    candidates: list[tuple[int, str, str, bool]] = []
    for left, right, display in ((r"\[", r"\]", True), (r"\(", r"\)", False), ("$$", "$$", True)):
        index = text.find(left, start)
        while index != -1:
            if left == "$$" or index == 0 or text[index - 1] != "\\":
                candidates.append((index, left, right, display))
                break
            index = text.find(left, index + 1)
    index = text.find("$", start)
    while index != -1:
        if is_unescaped_dollar(text, index) and not text.startswith("$$", index):
            candidates.append((index, "$", "$", False))
            break
        index = text.find("$", index + 1)
    return min(candidates, key=lambda item: item[0]) if candidates else None


def render_text_math(value: Any, renderer: MathRenderer, *, normalize: bool = False) -> str:
    text = normalize_source_latex(value) if normalize else str(value or "")
    output: list[str] = []
    cursor = 0
    while cursor < len(text):
        found = find_next_delimiter(text, cursor)
        if not found:
            output.append(render_plain_text(text[cursor:], renderer))
            break
        start, left, right, display = found
        output.append(render_plain_text(text[cursor:start], renderer))
        expr_start = start + len(left)
        end = text.find(right, expr_start)
        if end == -1:
            output.append(html.escape(text[start:]))
            break
        tex = text[expr_start:end]
        output.append(renderer.add(tex, display=display))
        cursor = end + len(right)
    return "".join(output)


def previous_line_start(text: str, index: int) -> int:
    return text.rfind("\n", 0, index) + 1


def bare_math_start(text: str, index: int) -> int:
    line_start = previous_line_start(text, index)
    prefix = text[line_start:index]
    if "=" in prefix:
        space = max(prefix.rfind(" "), prefix.rfind("\t"))
        return line_start + space + 1
    return index


def bare_math_end(text: str, index: int) -> int:
    stops = [
        ". ",
        ".\n",
        "; ",
        "; \n",
        " and identify",
        " and determine",
        " and calculate",
        " and find",
        " and give",
        ", e.g.",
    ]
    positions = [text.find(stop, index) for stop in stops]
    positions = [position for position in positions if position != -1]
    if not positions:
        line_end = text.find("\n", index)
        return len(text) if line_end == -1 else line_end
    end = min(positions)
    if text.startswith(". ", end) or text.startswith(".\n", end):
        return end + 1
    return end


def render_plain_text(value: str, renderer: MathRenderer) -> str:
    output: list[str] = []
    cursor = 0
    command_pattern = re.compile(r"\\[A-Za-z]+")
    while cursor < len(value):
        match = command_pattern.search(value, cursor)
        if not match:
            output.append(html.escape(value[cursor:]))
            break
        start = bare_math_start(value, match.start())
        if start < cursor:
            start = match.start()
        output.append(html.escape(value[cursor:start]))
        end = bare_math_end(value, match.end())
        tex = value[start:end].strip()
        if tex:
            output.append(renderer.add(tex, display=False))
        cursor = end
    return "".join(output)


def render_answer(value: Any, renderer: MathRenderer) -> str:
    answer = str(value or "").strip()
    if not answer:
        return '<span class="empty">(empty)</span>'
    if re.match(r"^\\begin\{(?:aligned|gathered|array|cases|split|matrix|pmatrix|bmatrix)", answer):
        return renderer.add(answer, display=True)
    if find_next_delimiter(answer, 0):
        return render_text_math(answer, renderer)
    return renderer.add(answer, display=True)


def render_judge_items(reason: str, renderer: MathRenderer) -> str:
    lines = [line.strip() for line in str(reason or "").splitlines() if line.strip()]
    if not lines:
        return '<p class="empty">(No judge rationale.)</p>'
    items = []
    for line in lines:
        match = re.match(r"^\(([^)]+)\)\s*(.*)$", line)
        if match:
            part, body = match.groups()
            content = f"<strong>({html.escape(part)})</strong> {render_text_math(body, renderer)}"
        else:
            content = render_text_math(line, renderer)
        items.append(f"<li>{content}</li>")
    return "<ul>" + "\n".join(items) + "</ul>"


def score_text(value: Any) -> str:
    if value is None:
        return "unscored"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)


def build_html(rows: list[dict[str, Any]]) -> str:
    renderer = MathRenderer()
    sections = []
    for index, row in enumerate(rows, start=1):
        result = row["evaluation_parts"]["merged"]
        sections.append(
            f"""
<section class="sample">
  <header class="sample-head">
    <div>
      <p class="dataset">{html.escape(row["dataset"])} · test · merged mode</p>
      <h2>{index}. {html.escape(str(row["id"]))}</h2>
    </div>
    <div class="score">Score {html.escape(score_text(row.get("score")))}</div>
  </header>

  <h3>Problem Statement</h3>
  <div class="text-block">{render_text_math(row.get("question", ""), renderer, normalize=True)}</div>

  <h3>Extracted Answer</h3>
  <div class="answer-block">{render_answer(result.get("extracted_answer", ""), renderer)}</div>

  <h3>Final Solution</h3>
  <div class="text-block">{render_text_math(row.get("solution", ""), renderer, normalize=True)}</div>

  <h3>Judge Rationale</h3>
  <div class="rationale">{render_judge_items(result.get("judge_reason", ""), renderer)}</div>
</section>
"""
        )

    document = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>GPT-5.5 Merged Evaluation Review Samples</title>
  <link rel="stylesheet" href="../../inspection/static/vendor/katex/katex.min.css" />
  <style>
    @page {{ size: letter; margin: 0.58in 0.52in; }}
    body {{
      color: #111827;
      font-family: "DejaVu Serif", "Liberation Serif", Georgia, serif;
      font-size: 10.2pt;
      line-height: 1.42;
    }}
    h1 {{ font-size: 20pt; margin: 0 0 0.15in; }}
    .subtitle {{ color: #475569; margin: 0 0 0.3in; }}
    .sample {{ break-before: page; }}
    .sample:first-of-type {{ break-before: avoid; }}
    .sample-head {{
      align-items: start;
      border-bottom: 1.5pt solid #1f2937;
      display: flex;
      justify-content: space-between;
      gap: 0.25in;
      margin-bottom: 0.18in;
      padding-bottom: 0.08in;
    }}
    .dataset {{
      color: #475569;
      font-family: "DejaVu Sans", "Liberation Sans", Arial, sans-serif;
      font-size: 8.2pt;
      font-weight: 700;
      letter-spacing: 0.02em;
      margin: 0 0 0.03in;
      text-transform: uppercase;
    }}
    h2 {{ font-size: 15pt; margin: 0; }}
    h3 {{
      color: #0f766e;
      font-family: "DejaVu Sans", "Liberation Sans", Arial, sans-serif;
      font-size: 9.2pt;
      margin: 0.18in 0 0.05in;
      text-transform: uppercase;
    }}
    .score {{
      background: #ecfdf5;
      border: 1pt solid #86efac;
      border-radius: 3pt;
      color: #14532d;
      font-family: "DejaVu Sans", "Liberation Sans", Arial, sans-serif;
      font-size: 9pt;
      font-weight: 700;
      padding: 0.05in 0.08in;
      white-space: nowrap;
    }}
    .text-block, .answer-block, .rationale {{
      border: 0.7pt solid #d1d5db;
      border-radius: 4pt;
      padding: 0.08in 0.1in;
      white-space: pre-wrap;
    }}
    .answer-block {{
      background: #fffdf2;
      font-size: 9.2pt;
    }}
    .text-block {{ background: #ffffff; }}
    .rationale {{ background: #f8fafc; }}
    .rationale ul {{ margin: 0; padding-left: 0.22in; }}
    .rationale li {{ margin: 0.02in 0; }}
    .katex {{ font-size: 1em; }}
    .katex-display {{
      margin: 0.07in 0;
      overflow: hidden;
    }}
    .answer-block .katex-display {{ font-size: 0.86em; }}
    .empty {{ color: #64748b; font-style: italic; }}
  </style>
</head>
<body>
  <h1>GPT-5.5 Merged Evaluation Review Samples</h1>
  <p class="subtitle">Random test-set samples from Physics and FrontierPhysics. Each sample shows the problem statement, extracted boxed answer, reference final solution, and GPT-5.5 judge rationale.</p>
  {''.join(sections)}
</body>
</html>
"""
    rendered = renderer.render_all()
    for index, item in enumerate(rendered):
        document = document.replace(f"@@MATH_{index}@@", item)
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "inspection" / "reviews" / "gpt-5.5_merged_random_review.json",
    )
    parser.add_argument(
        "--html-output",
        type=Path,
        default=REVIEW_DIR / "gpt-5.5_merged_random_review.html",
    )
    parser.add_argument(
        "--pdf-output",
        type=Path,
        default=REVIEW_DIR / "gpt-5.5_merged_random_review.pdf",
    )
    args = parser.parse_args()

    rows = json.loads(args.input.read_text(encoding="utf-8"))
    document = build_html(rows)
    args.html_output.write_text(document, encoding="utf-8")
    HTML(string=document, base_url=str(args.html_output.parent)).write_pdf(args.pdf_output)
    print(f"Wrote {args.html_output}")
    print(f"Wrote {args.pdf_output}")


if __name__ == "__main__":
    main()
