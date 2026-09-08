#!/usr/bin/env python3
"""Check distinct human reviewers, explicit overrides, and processed provenance."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path

from process_audits import AUDIT_DIR, LABELS, process_audits, read_audits, read_overrides


def validate(raw_path: Path, processed_path: Path, overrides_path: Path) -> dict:
    fields, raw = read_audits(raw_path)
    overrides = read_overrides(overrides_path)
    if not raw or "reviewer_id" not in raw[0] or "submitted_at" not in raw[0]:
        raise ValueError("Raw audits must identify reviewers and submitted reviews")
    groups = defaultdict(list)
    annotations = set()
    for row in raw:
        if row["label"] not in LABELS or not row["reviewer_id"].strip() or not row["submitted_at"].strip():
            raise ValueError("Every raw audit needs a known label, reviewer ID, and submission time")
        if not row["annotation_id"] or row["annotation_id"] in annotations:
            raise ValueError("Missing or duplicate annotation ID")
        annotations.add(row["annotation_id"])
        groups[row["dataset"], row["source_problem_id"]].append(row)
    with processed_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != fields:
            raise ValueError("Processed columns differ from the audit processor's output")
        processed = list(reader)
    expected, conflicts = process_audits(raw, fields, overrides)
    # CSV readers must preserve embedded newlines; only normalize line endings.
    def normalized(rows):
        return [{k: v.replace("\r\n", "\n") for k, v in row.items()} for row in rows]
    if normalized(processed) != normalized(expected):
        raise ValueError("Processed audits do not reproduce from raw reviews and overrides")
    if len({(r['dataset'], r['source_problem_id']) for r in processed}) != len(processed):
        raise ValueError("Processed audits contain duplicate/unresolved problems")
    unused = sorted(set(overrides) - set(groups))
    if unused:
        raise ValueError(f"Overrides refer to absent problems: {unused}")
    problems, counts = [], defaultdict(Counter)
    final = {(r['dataset'], r['source_problem_id']): r['label'] for r in processed}
    for key, reviews in sorted(groups.items()):
        reviewers = {r['reviewer_id'].strip() for r in reviews}
        disagreement = len({r['label'] for r in reviews}) > 1
        overridden = key in overrides
        violations = []
        if len(reviewers) < 2 and not overridden:
            violations.append("fewer_than_two_reviewers_without_override")
        # Even a third-pass majority does not satisfy the explicit-override rule.
        if disagreement and not overridden:
            violations.append("disagreement_without_override")
        item = dict(dataset=key[0], source_problem_id=key[1], display_id=reviews[0]['display_id'],
                    reviews=len(reviews), distinct_reviewers=len(reviewers),
                    original_labels=[r['label'] for r in reviews], label=final[key],
                    disagreement=disagreement, override=overridden, violations=violations)
        problems.append(item)
        c = counts[key[0]]
        c.update(problems=1, reviews=len(reviews), two_or_more_reviewers=int(len(reviewers) >= 2),
                 single_reviewer=int(len(reviewers) == 1), disagreements=int(disagreement),
                 overrides=int(overridden), single_with_override=int(len(reviewers) == 1 and overridden),
                 missing_single_override=int(len(reviewers) < 2 and not overridden),
                 missing_conflict_override=int(disagreement and not overridden), violations=int(bool(violations)))
    totals = Counter()
    for c in counts.values():
        totals.update(c)
    return dict(passed=totals['violations'] == 0, summary=dict(totals),
                datasets={k: dict(v) for k, v in counts.items()}, problems=problems,
                processor_summary=conflicts['summary'],
                source_sha256={str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (raw_path, processed_path, overrides_path)})


def write_report(report: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    lines = ['# Reviewer coverage audit', '',
             '**PASS**' if report['passed'] else '**FAIL: reviewer coverage is incomplete.**', '',
             'Distinct reviewers are counted from submitted raw annotations, not processed rows or AI audits.',
             'Every disagreement requires an explicit override, including third-pass resolutions.', '',
             '| Dataset | Problems | ≥2 reviewers | One reviewer | One + override | Missing override | Conflicts | Conflict overrides missing |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for ds, c in [*report['datasets'].items(), ('Total', report['summary'])]:
        fields = ['problems', 'two_or_more_reviewers', 'single_reviewer', 'single_with_override',
                  'missing_single_override', 'disagreements', 'missing_conflict_override']
        lines.append('| ' + ds + ' | ' + ' | '.join(str(c[f]) for f in fields) + ' |')
    lines += ['', '## Problems requiring a second review or explicit expert override', '',
              '| Dataset | Display ID | Source problem ID | Current label | Issue |', '|---|---:|---|---|---|']
    for p in report['problems']:
        if p['violations']:
            lines.append(f"| {p['dataset']} | {p['display_id']} | `{p['source_problem_id']}` | {p['label']} | {', '.join(p['violations'])} |")
    lines += ['', 'Processed rows reproduce from raw reviews and overrides (allowing newline normalization).',
              'The companion JSON records every problem and SHA-256 hashes of the input files.',
              'This checks recorded provenance and coverage; it does not invent reviews or certify the scientific verdicts.', '']
    output.with_suffix('.md').write_text('\n'.join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', type=Path, default=AUDIT_DIR / 'audits.csv')
    parser.add_argument('--processed', type=Path, default=AUDIT_DIR / 'audits_processed.csv')
    parser.add_argument('--overrides', type=Path, default=AUDIT_DIR / 'audit-overrides.json')
    parser.add_argument('--report', type=Path, default=AUDIT_DIR / 'reports/reviewer_coverage')
    args = parser.parse_args()
    report = validate(args.raw, args.processed, args.overrides)
    write_report(report, args.report)
    print(json.dumps(report['summary'], indent=2))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
