#!/usr/bin/env python3
"""Build evaluation verdicts from manually adjudicated expert reviews.

verdict_review.json records decisions, unresolved questions, and reviewed source
hashes. Changed sources require a fresh manual review before regenerating.
Unresolved cases are excluded from verdicts.json and listed in
verdict_ambiguities.csv. Run with --dry-run to validate without writing.
"""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

from solution_layout import challenge_folder


BASE = Path(__file__).resolve().parents[1]


def build_verdicts(base):
    review = json.loads((base / "verdict_review.json").read_text())
    for relative, checksum in review["source_sha256"].items():
        path = base / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise ValueError(f"Reviewed source changed; adjudicate again before exporting: {relative}")
    with (base / "annotations.csv").open(encoding="utf-8-sig", newline="") as source:
        submitted = {challenge_folder(row["Challenge ID"]) for row in csv.DictReader(source)}
    if set(review["challenges"]) != submitted:
        raise ValueError("Adjudication must cover every reviewed challenge and no unreviewed challenges")

    verdicts = {}
    ambiguities = []
    for challenge, decision in sorted(review["challenges"].items()):
        verdict = decision.get("verdict")
        if verdict is None:
            if not decision.get("question_for_expert") or not decision.get("reason"):
                raise ValueError(f"Missing clarification question/reason for {challenge}")
            ambiguities.append({"challenge": challenge, "reason": decision["reason"],
                                "question_for_expert": decision["question_for_expert"]})
            continue
        if "question_for_expert" in decision:
            raise ValueError(f"Unresolved challenge cannot have an evaluation verdict: {challenge}")
        if set(verdict) != {"problem", "model"}:
            raise ValueError(f"Invalid verdict fields for {challenge}")
        problem, model = verdict["problem"], verdict["model"]
        if problem not in {"clean", "repairable", "unrepairable"}:
            raise ValueError(f"Invalid problem verdict for {challenge}")
        if model not in {"correct", "incorrect", "none"} or (
                problem == "clean" and model == "none") or (
                problem == "unrepairable" and model != "none"):
            raise ValueError(f"Invalid problem/model combination for {challenge}")
        if problem == "repairable":
            if not (base / "solutions" / challenge / "problem.tex").is_file():
                raise ValueError(f"Repairable challenge lacks its corrected statement: {challenge}")
        if not decision.get("reason"):
            raise ValueError(f"Missing decision rationale for {challenge}")
        verdicts[challenge] = verdict

    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["challenge", "reason", "question_for_expert"],
                            lineterminator="\n")
    writer.writeheader()
    writer.writerows(ambiguities)
    return verdicts, output.getvalue(), len(ambiguities)


def main():
    from update_annotations import atomic_write

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    verdicts, ambiguities, pending = build_verdicts(BASE)
    if not args.dry_run:
        atomic_write(BASE / "verdicts.json", (json.dumps(verdicts, indent=2) + "\n").encode())
        atomic_write(BASE / "verdict_ambiguities.csv", ambiguities.encode())
    print(f"{len(verdicts)} evaluation verdicts; {pending} require expert clarification"
          + (" (dry run)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
