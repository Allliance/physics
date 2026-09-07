#!/usr/bin/env python3
"""Apply the curated expert follow-up, then refresh provenance and verdicts.

The plan in expert_clarifications.json records the user-supplied decisions and
exact accepted file contents. It may be reapplied without duplicating content.
Inputs must match either the reviewed pre-change state or the accepted output.
"""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

from build_verdicts import build_verdicts
from export_expert_reviews import build_expert_reviews, write_expert_reviews
from update_annotations import atomic_write, parse_rows


BASE = Path(__file__).resolve().parents[1]


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def apply_clarifications(base, dry_run=False):
    plan = json.loads((base / "expert_clarifications.json").read_text())
    report_path = base / "solution_normalization_report.json"
    review_path = base / "verdict_review.json"
    review = json.loads(review_path.read_text())
    manifest_path = base / "solutions/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    report = (json.loads(report_path.read_text()) if report_path.exists()
              else manifest.get("normalization"))
    if report is None:
        # The generated report was deliberately removed. Recover only the
        # canonical integrity metadata from the reviewed snapshot, not a new report.
        rows = []
        for number in range(71):
            challenge = f"{number:02d}"
            items = {}
            for role in ("problem", "solution", "final_answer"):
                relative = f"solutions/{challenge}/{role}.tex"
                if relative in review["source_sha256"]:
                    items[role] = {"path": f"{challenge}/{role}.tex",
                                   "sha256": review["source_sha256"][relative]}
            rows.append({"challenge": challenge, "files": items,
                         "missing": [role + ".tex" for role in ("problem", "solution", "final_answer") if role not in items],
                         "exceptions": []})
        report = {"challenges": rows, "source_policy": "Removed source uploads; canonical hashes retained in the manifest."}
    outputs = {}
    for relative, patch in plan["files"].items():
        parts = Path(relative).parts
        if len(parts) != 3 or parts[0] != "solutions" or parts[1] not in plan["comments"] or parts[2] not in {
                "problem.tex", "solution.tex", "final_answer.tex"}:
            raise ValueError(f"Invalid curated file path: {relative}")
        path = base / relative
        data = patch["content"].encode()
        existing = checksum(path.read_bytes()) if path.exists() else None
        if existing not in (patch["before_sha256"], checksum(data)):
            raise ValueError(f"Unreviewed edit to {relative}; refusing to overwrite")
        outputs[relative] = data
    # Do not silently bless unrelated new annotations or edits as reviewed.
    for relative, old_hash in review["source_sha256"].items():
        if relative in outputs or relative in {"solution_normalization_report.json", "expert_clarifications.json"}:
            continue
        if relative.startswith("solutions/") and relative.endswith("/expert_review.txt") and Path(relative).parts[1] in plan["comments"]:
            continue
        if checksum((base / relative).read_bytes()) != old_hash:
            raise ValueError(f"Other reviewed source changed: {relative}")
    if dry_run:
        return len(outputs)

    for relative, data in outputs.items():
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, data)
    for row in report["challenges"]:
        challenge = row["challenge"]
        if challenge not in plan["comments"]:
            continue
        row["curation"] = {"source": "expert_clarifications.json", "authority": plan["authority"]}
        for role in ("problem", "solution", "final_answer"):
            relative = f"solutions/{challenge}/{role}.tex"
            if relative not in outputs:
                continue
            patch = plan["files"][relative]
            row["files"][role] = {
                "source": patch["source"], "source_sha256": patch["source_sha256"],
                "action": patch["action"], "path": f"{challenge}/{role}.tex",
                "sha256": checksum(outputs[relative]),
            }
        row["missing"] = [role + ".tex" for role in ("problem", "solution", "final_answer") if role not in row["files"]]
        row["exceptions"] = (["Missing: " + ", ".join(row["missing"]) + "."] if row["missing"] else [])
        row["exceptions"] += plan.get("artifact_notes", {}).get(challenge, [])
    report["canonical_files"] = sum(len(row["files"]) for row in report["challenges"])
    report["complete_challenges"] = sum(not row["missing"] for row in report["challenges"])
    manifest["normalization"] = report
    atomic_write(manifest_path, (json.dumps(manifest, indent=2) + "\n").encode())
    if report_path.exists():
        atomic_write(report_path, (json.dumps(report, indent=2) + "\n").encode())
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["challenge", "exception"])
    for row in report["challenges"]:
        writer.writerows((row["challenge"], note) for note in row["exceptions"])
    if (base / "solution_normalization_exceptions.csv").exists():
        atomic_write(base / "solution_normalization_exceptions.csv", output.getvalue().encode())

    with (base / "annotations.csv").open(encoding="utf-8-sig", newline="") as source:
        headers, records = parse_rows(list(csv.reader(source)))
    write_expert_reviews(base / "solutions", build_expert_reviews(headers, records))
    for challenge, decision in plan["decisions"].items():
        item = review["challenges"][challenge]
        if "verdict" not in decision:
            item.pop("verdict", None)
        if "question_for_expert" not in decision:
            item.pop("question_for_expert", None)
        item.update(decision)
        item["authority"] = "expert_clarifications.json"
    review["policy"].update(plan.get("verdict_policy", {}))
    review["policy"]["follow_up"] = (
        "User-relayed expert clarification authorizes the listed statement repairs and ground truths. "
        "The model label continues to judge the original AI answer."
    )
    paths = set(review["source_sha256"]) | set(outputs) | {"expert_clarifications.json"}
    if not report_path.exists():
        paths.discard("solution_normalization_report.json")
    review["source_sha256"] = {relative: checksum((base / relative).read_bytes()) for relative in sorted(paths)}
    atomic_write(review_path, (json.dumps(review, indent=2, ensure_ascii=False) + "\n").encode())
    verdicts, ambiguities, pending = build_verdicts(base)
    atomic_write(base / "verdicts.json", (json.dumps(verdicts, indent=2) + "\n").encode())
    atomic_write(base / "verdict_ambiguities.csv", ambiguities.encode())
    print(f"Applied {len(outputs)} file selections/patches; {len(verdicts)} verdicts, {pending} pending.")
    return len(outputs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    count = apply_clarifications(BASE, args.dry_run)
    if args.dry_run:
        print(f"Validated {count} curated file selections/patches (no writes).")
