#!/usr/bin/env python3
"""Export audited problem/ground_truth pairs for a text-based judge.

Run from any directory. The output has exactly three string fields, with rows in
ascending challenge order. Unreviewed, unresolved and unrepairable challenges,
and challenges without a final answer, are omitted and reported on stdout.
Corrected problem.tex takes precedence over the archived original statement.
ground_truth comes from final_answer.tex, regardless of original model verdict,
with necessary definitions/explanations from its audited solution.tex.

The reviewed source hashes are checked before export. Source-specific edits
below remove reviewer/solution appendices and retain their necessary problem
conventions. They affect the export only; source TeX remains intact. Python
parsing templates are not used. TeX math is retained, with local macros expanded
so exported formulas do not depend on an omitted document preamble.
"""

import argparse
import json
import re
from pathlib import Path

from build_verdicts import build_verdicts
from update_annotations import atomic_write


BASE = Path(__file__).resolve().parents[1]
COMMAND = re.compile(r"\\([A-Za-z]+)\*?")
DEFAULT_MACROS = {
    "chg": (1, "#1"),
    "tr": (0, r"\operatorname{tr}"),
}


def argument(text, position):
    """Read one TeX argument without losing nested braces or unbraced tokens."""
    while position < len(text) and text[position].isspace():
        position += 1
    if position == len(text):
        raise ValueError("Missing TeX argument")
    if text[position] != "{":
        match = re.match(r"\\(?:[A-Za-z]+|.)", text[position:])
        end = position + (len(match[0]) if match else 1)
        return text[position:end], end
    start = position + 1
    depth = 1
    position = start
    while position < len(text):
        if text[position] == "\\":
            # Escaped braces do not delimit a group; \\ is a token as well.
            position += 2
            continue
        if text[position] == "{":
            depth += 1
        elif text[position] == "}":
            depth -= 1
            if depth == 0:
                return text[start:position], position + 1
        position += 1
    raise ValueError("Unclosed TeX argument")


def expand_macros(text, macros):
    for _ in range(12):
        pieces = []
        position = 0
        for match in COMMAND.finditer(text):
            if match.start() < position or match[1] not in macros:
                continue
            count, body = macros[match[1]]
            end = match.end()
            for number in range(1, count + 1):
                value, end = argument(text, end)
                body = body.replace(f"#{number}", value)
            pieces.extend((text[position:match.start()], body))
            position = end
        pieces.append(text[position:])
        expanded = "".join(pieces)
        if expanded == text:
            return text
        text = expanded
    raise ValueError("Recursive or excessively nested TeX macros")


def text_body(raw):
    # Comments are not part of the rendered statement. Keep escaped percent signs.
    raw = re.sub(r"(?<!\\)%[^\n]*", "", raw)
    macros = dict(DEFAULT_MACROS)
    for match in re.finditer(r"\\(?:newcommand|renewcommand|providecommand)\*?", raw):
        name, end = argument(raw, match.end())
        arity = re.match(r"\s*\[(\d+)\]", raw[end:])
        count = int(arity[1]) if arity else 0
        if arity:
            end += arity.end()
        body, _ = argument(raw, end)
        macros[name.lstrip("\\")] = (count, body)
    if r"\begin{document}" in raw:
        raw = raw.split(r"\begin{document}", 1)[1].split(r"\end{document}", 1)[0]
    elif re.search(r"\\(?:newcommand|documentclass|usepackage)", raw):
        raise ValueError("Unexpected preamble without a document body")

    # Unwrap layout-only groups without touching ordinary mathematical braces.
    for _ in range(100):
        group = re.search(r"\{\s*\\color\{[^}]+\}", raw)
        if not group:
            break
        body, end = argument(raw, group.start())
        body = re.sub(r"^\s*\\color\{[^}]+\}", "", body)
        raw = raw[:group.start()] + body + raw[end:]
    for _ in range(100):
        box = re.search(r"\\adjustbox\b", raw)
        if not box:
            break
        _, end = argument(raw, box.end())
        body, end = argument(raw, end)
        body = body.strip()
        if body.startswith("$") and body.endswith("$"):
            body = body[1:-1]
        raw = raw[:box.start()] + body + raw[end:]

    # Expand presentation macros as identity, preserving their revised content.
    macros.update({"chg": (1, "#1"), "fitmath": (1, "#1"), "textcolor": (2, "#2"),
                   "color": (1, ""), "maketitle": (0, ""),
                   "noindent": (0, "")})
    raw = expand_macros(raw, macros)
    raw = re.sub(r"^.*\\textbf\{(?:Problem ID:|Primary inferred discipline:|"
                 r"Secondary inferred disciplines:|Python implementation:).*\n?",
                 "", raw, flags=re.MULTILINE)

    # Keep descriptive headings, omit dossier metadata and redundant role titles.
    pieces = []
    position = 0
    heading = re.compile(r"\\(?:section|subsection|subsubsection|paragraph|subparagraph)\*?(?:\[[^\n]*?\])?")
    for match in heading.finditer(raw):
        if match.start() < position:
            continue
        title, end = argument(raw, match.end())
        omit = (title.startswith("Challenge ") or title.lower().rstrip(":") in {
            "problem", "problem setup", "final answer", "statement", "statement and strategy",
            "problem statement and interpretation", "high energy \\& nuclear physics",
            "statistical physics \\& thermodynamics", "atomic, molecular \\& optical",
            "quantum information, science \\& technology", "fluid dynamics",
        })
        pieces.extend((raw[position:match.start()], "\n\n" if omit else f"\n\n{title.rstrip(':')}:\n"))
        position = end
    pieces.append(raw[position:])
    raw = "".join(pieces)
    raw = re.sub(r"[ \t]+\n", "\n", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw).strip()
    # A whole-document color group is harmless but unnecessary in plain text.
    if raw.startswith("{"):
        body, end = argument(raw, 0)
        if not raw[end:].strip():
            raw = body.strip()
    return raw


def cut_at(text, marker):
    if text.count(marker) != 1:
        raise ValueError(f"Reviewed extraction marker changed: {marker}")
    return text.split(marker, 1)[0].rstrip()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Reviewed statement text changed: {old[:70]}")
    return text.replace(old, new, 1)


def prepare_problem(challenge, raw):
    """Retain the accepted task, excluding appended review and answer material."""
    if challenge in {"01", "08"}:
        raw = cut_at(raw, r"\section*{\chg{Issues found in the statement and how they are handled}}")
        if challenge == "01":
            raw += r"""

Use the curvature conventions $R^\rho{}_{\sigma\mu\nu}
=\partial_\mu\Gamma^\rho_{\nu\sigma}-\partial_\nu\Gamma^\rho_{\mu\sigma}
+\Gamma^\rho_{\mu\lambda}\Gamma^\lambda_{\nu\sigma}
-\Gamma^\rho_{\nu\lambda}\Gamma^\lambda_{\mu\sigma}$ and
$R_{\mu\nu}=R^\rho{}_{\mu\rho\nu}$, with positive scalar curvature on round
spheres and a Euclidean boundary metric. Interpret the anomaly convention as
$Z[\gamma^{(0)}]=e^{-\mathcal A_k}Z[\mathcal B^{-2}\gamma^{(0)}]$.
"""
        else:
            # These conventions are stated in the removed appendix. Its computed
            # coefficients and numerical answers must not appear in the prompt.
            raw += r"""

Use the action normalizations
\[
\mathcal S_{EH}=-\frac{M_{Pl}^2}{4}\int\epsilon_{ABCD}e^A\wedge e^B\wedge R^{CD},
\qquad
\mathcal S_\vartheta=\int\left[\frac12\star d\vartheta\wedge d\vartheta
-\frac1{3!}\epsilon_{ABCD}e^A\wedge e^B\wedge e^C\wedge e^D\,V\right].
\]
The signature is $(+,-,-,-)$, $\epsilon_{0123}=1$, and the spatial symbol is
$\epsilon^i{}_{jk}=\epsilon_{ijk}=\epsilon_{0ijk}$.
Read $\delta_{ia}$ in the spatial tetrad as $\delta^a_i$.
Keep the factor $(1+3n^2f^2)$ in the requested expression exactly as written.
"""
    elif challenge in {"07", "22"}:
        raw = cut_at(raw, "\n{\n\\color{blue}\n\\paragraph*{Issue")
        if challenge == "07":
            raw = replace_once(raw,
                "Suppose that the global GHZ state is in a depolarized form, with GHZ fidelity $F(n)=Fk^{n-1}$.",
                r"Take the initial state to be globally depolarized: "
                r"$\rho_0=(1-p)|\mathrm{GHZ}_{nd}\rangle\langle\mathrm{GHZ}_{nd}|"
                r"+pI/2^{nd}$. Its fidelity with the pure GHZ state is "
                r"$\langle\mathrm{GHZ}_{nd}|\rho_0|\mathrm{GHZ}_{nd}\rangle=F(n)=Fk^{n-1}$, "
                r"where $F$ and $k$ are fixed scalar parameters and the state is assumed physical.")
        else:
            # The accepted final answer uses a scalar optimization at fixed theta,
            # not the reviewer's alternative sketch about classical support.
            raw = replace_once(raw,
                "Write the maximal value in terms of an optimization $\\max_{x\\in[0,1]} f(x)$, where $f(x)$ depends only on $x$ and nothing else. Find the function form of $f(x)$ explicitly.",
                r"For fixed $\theta$, express the maximum Holevo information as "
                r"$\max_{x\in[0,1]}f(x)$ and find $f$ explicitly. Here $x$ is a scalar "
                r"optimization variable, distinct from the classical ensemble label; "
                r"$\theta$ remains a fixed parameter of $f$. Use base-2 logarithms "
                r"and the convention $0\log_2 0=0$.")
    elif challenge == "39":
        raw = cut_at(raw, r"\begin{tcolorbox}")
        raw += "\nFind the long-time reduced cavity state reached from the stated initial condition.\n"
    elif challenge == "40":
        start = raw.index(r"\begin{quote}")
        end = raw.index(r"\end{quote}", start) + len(r"\end{quote}")
        raw = raw[:start] + raw[end:]
    return text_body(raw)


def prepare_ground_truth(challenge, raw, folder):
    text = text_body(raw)
    if challenge == "02":
        text = replace_once(text,
            r"(\mathrm{answer}_{\beta},\mathrm{answer}_{\sigma^2})=(\mathrm{C},\mathrm{C})",
            r"\text{Neither }\beta\text{ nor }\sigma^2\text{ affects the population growth rate.}")
        solution = (folder / "solution.tex").read_text()
        if "Neither changes the asymptotic population growth rate to first order." not in solution:
            raise ValueError("Challenge 02's audited explanation changed")
        text += "\n\nThe coefficient of the first-order division-noise correction is zero."
    elif challenge == "20":
        solution = (folder / "solution.tex").read_text()
        eccentricity = r"e=\sqrt{1-b^{2}/a^{2}}"
        intensity = r"I_0=\frac{2P_0}{\pi w_0^{2}}"
        if eccentricity not in solution or intensity not in solution:
            raise ValueError("Challenge 20's audited definitions changed")
        text = (f"The eccentricity is ${eccentricity}$ and the peak intensity is "
                f"${intensity}$.\n\n" + text)
    elif challenge == "33":
        solution = (folder / "solution.tex").read_text()
        if "the stipulated transition criterion selects no particles in that regime" not in solution:
            raise ValueError("Challenge 33's audited conclusion changed")
        text = text.replace(r"\mathrm{NaN}", r"\text{undefined}")
        text += ("\n\nThe stipulated transition criterion selects no particles for "
                 "$r>r_o$. The requested numerical quantities cannot be determined "
                 "from the inconsistent and underdetermined constraints; "
                 "undefined is the audited conclusion, not a missing reference value.")
    elif challenge == "51":
        solution = (folder / "solution.tex").read_text()
        special_case = r"\Omega(x,2,1)=\frac{2}{\pi}K(4x)"
        if special_case not in solution:
            raise ValueError("Challenge 51's audited non-elementarity example changed")
        text += (f"\n\nThis is not elementary in general: ${special_case}$ for "
                 r"$|x|<1/4$, where $K$ is the complete elliptic integral of the first kind.")
    elif challenge == "62":
        if r"k_{\mathrm{value}}" not in text:
            raise ValueError("Challenge 62's branch-selection notation changed")
        text = text.replace(r"k_{\mathrm{value}}", "k")
    return text


def build_corrected_challenges(base):
    verdicts, _, _ = build_verdicts(base)
    persisted = json.loads((base / "verdicts.json").read_text())
    if verdicts != persisted:
        raise ValueError("verdicts.json is stale; regenerate it before exporting")
    reviewed = json.loads((base / "verdict_review.json").read_text())["challenges"]
    originals = {}
    for line in (base / "original_challenges.jsonl").read_text().splitlines():
        row = json.loads(line)
        challenge = f"{int(row['challenge_id'].removeprefix('Challenge_')):02d}"
        if challenge in originals:
            raise ValueError(f"Duplicate original challenge: {challenge}")
        originals[challenge] = row
    if not set(reviewed) <= set(originals):
        raise ValueError("Reviewed challenge missing from original archive")

    rows, included, excluded = [], [], {}
    for challenge, original in sorted(originals.items()):
        if challenge not in reviewed:
            excluded[challenge] = "unaudited"
            continue
        if challenge not in verdicts:
            excluded[challenge] = "unresolved audit"
            continue
        verdict = verdicts[challenge]
        if verdict["problem"] == "unrepairable":
            excluded[challenge] = "unrepairable problem"
            continue
        folder = base / "solutions" / challenge
        answer_path = folder / "final_answer.tex"
        if not answer_path.exists():
            excluded[challenge] = "missing audited final answer"
            continue
        problem_path = folder / "problem.tex"
        if problem_path.exists():
            problem = prepare_problem(challenge, problem_path.read_text())
        else:
            if verdict["problem"] != "clean":
                raise ValueError(f"Missing repaired statement: {challenge}")
            problem = original.get("problem", original.get("problem_description", "")).strip()
        ground_truth = prepare_ground_truth(challenge, answer_path.read_text(), folder)
        if not problem or not ground_truth:
            raise ValueError(f"Empty problem or answer: {challenge}")
        for text in (problem, ground_truth):
            if re.search(r"\\(?:input|include|includegraphics|lstinputlisting)\b", text):
                raise ValueError(f"Unresolved external TeX dependency: {challenge}")
        if re.search(r"Python implementation|How I would have solved|Disclosure:|"
                     r"Issues? (?:found in|with) the problem|FILL IN YOUR RESULTS|def answer\(", problem):
            raise ValueError(f"Non-problem content remains in {challenge}")
        rows.append({"challenge_id": challenge, "problem": problem, "ground_truth": ground_truth})
        included.append(challenge)
    return rows, included, excluded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    rows, included, excluded = build_corrected_challenges(BASE)
    destination = BASE / "corrected_challenge.jsonl"
    if not args.dry_run:
        atomic_write(destination, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode())
    print(f"{'Validated' if args.dry_run else 'Wrote'} {len(rows)} audited problem/ground_truth pairs: {destination}")
    print("Row order: " + ", ".join(included))
    for reason in sorted(set(excluded.values())):
        print(reason + ": " + ", ".join(k for k, v in excluded.items() if v == reason))


if __name__ == "__main__":
    main()
