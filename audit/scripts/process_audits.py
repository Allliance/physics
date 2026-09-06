#!/usr/bin/env python3
"""Select representative audits and report disagreements for manual review."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


AUDIT_DIR = Path(__file__).resolve().parents[1]
DROP_COLUMNS = {
    "review_time_seconds", "review_timer_started_at",
    "review_tracking_expected_at", "reviewer_id", "assigned_at", "submitted_at",
}
REQUIRED_COLUMNS = {
    "annotation_id", "display_id", "source_problem_id", "dataset",
    "category", "pass", "label", "note",
}
LABELS = {"PROBLEM_FAILURE", "GRADER_FAILURE", "MODEL_FAILURE"}


def read_audits(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        missing = REQUIRED_COLUMNS - set(fields)
        if missing:
            raise ValueError(f"Missing required CSV columns: {sorted(missing)}")
        if len(fields) != len(set(fields)):
            raise ValueError("Duplicate CSV column names")
        rows = list(reader)
    for index, row in enumerate(rows, start=1):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Malformed CSV audit record {index}")
        if not row["dataset"] or not row["source_problem_id"] or not row["label"]:
            raise ValueError(f"Missing problem identity or label in audit record {index}")
        if row["pass"] not in {"1", "2", "3"}:
            raise ValueError(f"Unsupported pass in audit record {index}: {row['pass']!r}")
    return [field for field in fields if field not in DROP_COLUMNS], rows


def read_overrides(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    """A missing/empty file means there are no manual resolutions yet."""
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError("Overrides must be a JSON list; see audit/README.md")
    overrides = {}
    for entry in entries:
        if not isinstance(entry, dict) or any(
            not isinstance(entry.get(field), str) or not entry[field].strip()
            for field in ("dataset", "source_problem_id", "label")
        ):
            raise ValueError("Each override needs dataset, source_problem_id, and label strings")
        if entry["label"] not in LABELS:
            raise ValueError(f"Unknown override label: {entry['label']!r}")
        if "note" in entry and not isinstance(entry["note"], str):
            raise ValueError("Override note must be a string")
        key = (entry["dataset"], entry["source_problem_id"])
        if key in overrides:
            raise ValueError(f"Duplicate override for {key}")
        overrides[key] = entry
    return overrides


def preferred(rows: list[dict[str, str]]) -> dict[str, str]:
    # max keeps the first item on ties, preserving the recorded CSV order.
    return max(rows, key=lambda row: len(row["note"]))


def process_audits(
    rows: list[dict[str, str]],
    fields: list[str],
    overrides: dict[tuple[str, str], dict[str, str]],
) -> tuple[list[dict[str, str]], dict]:
    groups = defaultdict(list)
    for row in rows:
        groups[(row["dataset"], row["source_problem_id"])].append(row)

    def clean(row):
        return {field: row[field] for field in fields}

    output = []
    conflicts = []
    for key, group in groups.items():
        passes = {row["pass"]: row for row in group}
        if len(passes) != len(group):
            raise ValueError(f"Multiple audits for the same pass for {key}")

        reason = None
        if "1" in passes and "2" in passes:
            first, second = passes["1"], passes["2"]
            if first["label"] == second["label"]:
                # Pass 3 is only used to adjudicate a disagreement.
                candidates = [row for row in group if row["pass"] in {"1", "2"}]
            elif "3" not in passes:
                reason = "Passes 1 and 2 disagree; pass 3 is missing."
            elif passes["3"]["label"] in {first["label"], second["label"]}:
                candidates = [row for row in group if row["label"] == passes["3"]["label"]]
            else:
                reason = "All three passes have different labels."
        elif len({row["label"] for row in group}) == 1:
            candidates = group
        else:
            reason = "Available passes disagree, and pass 1 or pass 2 is missing."

        override = overrides.get(key)
        if reason is None and override is None:
            output.append(clean(preferred(candidates)))
            continue

        conflict = {
            "dataset": key[0],
            "source_problem_id": key[1],
            "display_id": group[0]["display_id"],
            "status": "resolved" if override else "unresolved",
            "reason": reason or "Manual override applied; no unresolved pass disagreement.",
            "audits": [clean(row) for row in group],
        }
        if override:
            matching = [row for row in group if row["label"] == override["label"]]
            selected = clean(preferred(matching) if matching else group[0])
            selected["label"] = override["label"]
            selected["note"] = override.get("note", selected["note"] if matching else "")
            output.append(selected)
            conflict["override"] = override
            conflict["resolved_audit"] = selected
        else:
            output.extend(clean(row) for row in group)
        conflicts.append(conflict)

    conflicts.sort(key=lambda conflict: conflict["status"] == "resolved")
    unresolved = sum(conflict["status"] == "unresolved" for conflict in conflicts)
    report = {
        "summary": {
            "input_audits": len(rows),
            "problems": len(groups),
            "output_audits": len(output),
            "unresolved_conflicts": unresolved,
            "resolved_conflicts": len(conflicts) - unresolved,
        },
        "conflicts": conflicts,
    }
    return output, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=AUDIT_DIR / "audits.csv")
    parser.add_argument("--output", type=Path, default=AUDIT_DIR / "audits_processed.csv")
    parser.add_argument("--conflicts", type=Path, default=AUDIT_DIR / "conflicts.json")
    parser.add_argument("--overrides", type=Path, default=AUDIT_DIR / "audit-overrides.json")
    args = parser.parse_args()
    paths = [args.input, args.overrides, args.output, args.conflicts]
    if len({path.resolve() for path in paths}) != len(paths):
        parser.error("Input, overrides, output, and conflicts paths must all be different")
    try:
        fields, rows = read_audits(args.input)
        output, report = process_audits(rows, fields, read_overrides(args.overrides))
    except (ValueError, OSError) as error:
        parser.error(str(error))
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output)
    args.conflicts.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = report["summary"]
    print(f"Wrote {len(output)} audits for {summary['problems']} problems to {args.output}")
    print(f"Manual review needed: {summary['unresolved_conflicts']} problems")
    print(f"Resolved by overrides: {summary['resolved_conflicts']} problems")
    print(f"Conflict details: {args.conflicts}")


if __name__ == "__main__":
    main()
