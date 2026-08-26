#!/usr/bin/env python3
"""Reproduce EED failures and build the detailed PHYBench equivalence report."""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "EED"))
from EED import EED  # noqa: E402


ARTIFACT = ROOT / "artifacts" / "gpt-5.6-sol-high-best-of-5"
AUDIT_PATH = ARTIFACT / "final_equivalence_audit.jsonl"
REVIEW_PATH = ARTIFACT / "equivalence_review.jsonl"
DATASET_PATH = ROOT / "data" / "PHYBench-fullques_v1.json"
DIAGNOSTICS_PATH = ARTIFACT / "eed_false_negative_diagnostics.jsonl"
REPORT_PATH = ARTIFACT / "false_negative_comprehensive_review.md"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def diagnose(reference: str, candidate: str, recorded_score: float) -> dict:
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            result = EED(reference, candidate, debug_mode=True)
    except Exception as exc:
        exception_type = type(exc).__name__
        stage = {
            "LaTeXError": "LATEX_PARSE_FAILURE",
            "SymPyError": "SYMPY_NORMALIZATION_FAILURE",
            "DistError": "TREE_DISTANCE_FAILURE",
        }.get(exception_type, "SCORER_EXCEPTION")
        return {
            "failure_stage": stage,
            "exception_type": exception_type,
            "exception": str(exc),
            "scorer_output": output.getvalue().strip(),
            "recorded_eed_score": recorded_score,
        }
    score, relative_distance, tree_size, distance = result
    return {
        "failure_stage": "TREE_EQUIVALENCE_FALSE_NEGATIVE",
        "exception_type": None,
        "exception": "",
        "scorer_output": output.getvalue().strip(),
        "recorded_eed_score": recorded_score,
        "reproduced_eed_score": float(score),
        "relative_distance": float(relative_distance),
        "tree_size": float(tree_size),
        "distance": float(distance),
    }


def failure_explanation(diagnostic: dict) -> str:
    stage = diagnostic["failure_stage"]
    if stage == "LATEX_PARSE_FAILURE":
        return (
            "The released EED preprocessor/parser could not convert the candidate and reference "
            "pair into SymPy. Its documented fallback is score 0, so symbolic equivalence was never tested."
        )
    if stage == "SYMPY_NORMALIZATION_FAILURE":
        return (
            "LaTeX parsing completed, but the released SymPy simplification/equality stage raised an "
            "error and returned 0. The tree comparison was never reached."
        )
    if stage == "TREE_DISTANCE_FAILURE":
        return (
            "The expressions reached tree construction, but the released edit-distance implementation "
            "failed and returned 0 instead of an equivalence verdict."
        )
    if stage == "TREE_EQUIVALENCE_FALSE_NEGATIVE":
        score = diagnostic.get("reproduced_eed_score", diagnostic["recorded_eed_score"])
        distance = diagnostic.get("distance")
        return (
            f"Parsing and simplification completed, but SymPy did not prove equality. EED compared the "
            f"remaining syntax trees and assigned score {score:.6g}"
            + (f" with tree distance {distance:g}." if distance is not None else ".")
            + " The algebraic/physical identity described above is outside that canonicalization path."
        )
    return "The released scorer raised an unclassified exception and did not establish equivalence."


def math_block(value: str) -> str:
    """Render a stored LaTeX answer as Markdown display math without nesting delimiters."""
    value = value.strip()
    for opening, closing in (("$$", "$$"), ("\\[", "\\]"), ("\\(", "\\)"), ("$", "$")):
        if value.startswith(opening) and value.endswith(closing):
            value = value[len(opening) : len(value) - len(closing)].strip()
            break
    return f"$$\n{value}\n$$"


def markdown_solution(value: str) -> str:
    """Contain malformed source math so it cannot break subsequent report sections."""
    value = value.strip()
    delimiter_count = sum(line.strip() == "$$" for line in value.splitlines())
    if delimiter_count % 2:
        value += "\n\n$$"
    return value


def main() -> int:
    audit = {
        item["id"]: item
        for item in read_jsonl(AUDIT_PATH)
        if item["verdict"] == "GRADER_FALSE_NEGATIVE"
    }
    reviews = {item["id"]: item for item in read_jsonl(REVIEW_PATH)}
    dataset = {
        str(item["id"]): item
        for item in json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    }

    diagnostics = []
    for item_id in sorted(audit, key=int):
        item = audit[item_id]
        review = reviews[item_id]
        accepted_ids = set(item["equivalent_candidate_ids"])
        accepted = [
            candidate for candidate in review["candidates"]
            if candidate["candidate_id"] in accepted_ids
        ]
        representative = accepted[0]
        diagnostic = diagnose(
            dataset[item_id]["answer"],
            representative["normalized_final_answer"],
            representative["eed_score"],
        )
        diagnostics.append(
            {
                "id": item_id,
                "representative_candidate_id": representative["candidate_id"],
                **diagnostic,
            }
        )
        print(f"diagnosed {item_id}: {diagnostic['failure_stage']}", flush=True)

    with DIAGNOSTICS_PATH.open("w", encoding="utf-8") as handle:
        for item in diagnostics:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    diagnostic_by_id = {item["id"]: item for item in diagnostics}

    stage_counts: dict[str, int] = {}
    for item in diagnostics:
        stage = item["failure_stage"]
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

    lines = [
        "# PHYBench Native-EED False-Negative Review",
        "",
        "This report covers the 39 questions that native EED marked unsolved even though at least one "
        "generated final answer was found equivalent after a two-pass adversarial review against the "
        "official answer and derivation. It reproduces the released scorer on one representative accepted "
        "answer per question. The review is model-assisted and auditable; it is not a formal human-expert certification.",
        "",
        "## Failure-stage summary",
        "",
        "| Failure stage | Questions |",
        "|---|---:|",
    ]
    labels = {
        "LATEX_PARSE_FAILURE": "LaTeX could not be converted to SymPy",
        "SYMPY_NORMALIZATION_FAILURE": "SymPy normalization/equality failed",
        "TREE_DISTANCE_FAILURE": "Tree-distance calculation failed",
        "TREE_EQUIVALENCE_FALSE_NEGATIVE": "Canonicalization missed equivalence; nonzero tree distance",
        "SCORER_EXCEPTION": "Other scorer exception",
    }
    for stage, count in sorted(stage_counts.items()):
        lines.append(f"| {labels.get(stage, stage)} | {count} |")
    lines.extend(["", "## Question-by-question findings", ""])

    for number, item_id in enumerate(sorted(audit, key=int), start=1):
        item = audit[item_id]
        review = reviews[item_id]
        source = dataset[item_id]
        diagnostic = diagnostic_by_id[item_id]
        accepted_ids = set(item["equivalent_candidate_ids"])
        accepted = [
            candidate for candidate in review["candidates"]
            if candidate["candidate_id"] in accepted_ids
        ]
        accepted_rounds = ", ".join(str(value) for value in item["equivalent_rounds"])
        lines.extend(
            [
                f"### {number}. PHYBench #{item_id} — {source['tag']}",
                "",
                f"**Verdict:** Native grader false negative. Equivalent round(s): {accepted_rounds}.",
                "",
                "**Question**",
                "",
                source["content"].strip(),
                "",
                "**Official reference answer**",
                "",
                math_block(source["answer"]),
                "",
                "**Accepted model answer variants**",
                "",
            ]
        )
        for candidate in accepted:
            rounds = [
                round_number for round_number, candidate_id in review["round_mapping"].items()
                if candidate_id == candidate["candidate_id"]
            ]
            lines.extend(
                [
                    f"Candidate {candidate['candidate_id']} (rounds {', '.join(rounds)}; native EED {candidate['eed_score']:.6g}):",
                    "",
                    math_block(candidate["final_answer"]),
                    "",
                ]
            )
        lines.extend(
            [
                "**Why the answer is equivalent**",
                "",
                item["reason"],
                "",
                "**Why native EED failed**",
                "",
                failure_explanation(diagnostic),
                "",
            ]
        )
        if diagnostic.get("exception"):
            lines.extend(
                [
                    f"Diagnostic exception: `{diagnostic['exception_type']}`. The full exception text is "
                    f"preserved in `{DIAGNOSTICS_PATH.name}`.",
                    "",
                ]
            )
        lines.extend(
            [
                "<details>",
                "<summary>Official solution used for adjudication</summary>",
                "",
                markdown_solution(source["solution"]),
                "",
                "</details>",
                "",
            ]
        )

    REPORT_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {REPORT_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
