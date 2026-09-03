# Physics Human Annotation Analysis

This directory is the workspace for analyzing expert human annotations on the
physics evaluation datasets. The goals are to measure problem and grader
failure modes, summarize reviewer feedback, check annotation coverage and
consistency, and produce reproducible inputs for dataset repair.

## Current inputs

The counts below describe the current local snapshot. They count annotation
records, not necessarily unique problems or reviewers.

| Source | Path | Format | Records | Description |
| --- | --- | --- | ---: | --- |
| CMT-Benchmark | `CMT-Benchmark/cmt_data_clean.json` | JSON | 50 | Audited problems, corrected prompts and solutions, issue types, and audit summaries |
| CritPt | `CritPt/annotations.csv` | CSV | 62 | Expert review form responses, confidence ratings, notes, and supporting uploads |
| PSet-Benchmarks | `PSet-Benchmarks/annotations.csv` | CSV | 285 | Problem-, model-, and grader-failure annotations across HLE Physics, PhyBench, PRISM, and UGPhysics |

These exports use different schemas and label vocabularies. Analyses should
normalize them explicitly rather than assuming that similarly named fields have
the same meaning.

## Directory layout

```text
analysis/
├── CMT-Benchmark/       # CMT audit data
├── CritPt/              # CritPt expert-review exports
├── PSet-Benchmarks/     # Cross-benchmark physics audit data
├── scripts/             # Reusable analysis and validation scripts
└── README.md
```

Keep reusable work in `scripts/`. Put temporary exploration in the repository's
top-level `scratch/` directory rather than committing notebooks or ad hoc
outputs here.

## Getting started

The source files can be inspected with the Python standard library:

```python
import csv
import json
from pathlib import Path

root = Path("analysis")

cmt_rows = json.loads(
    (root / "CMT-Benchmark" / "cmt_data_clean.json").read_text()
)

with (root / "CritPt" / "annotations.csv").open(
    encoding="utf-8-sig", newline=""
) as csv_file:
    critpt_rows = list(csv.DictReader(csv_file))

with (root / "PSet-Benchmarks" / "annotations.csv").open(
    encoding="utf-8-sig", newline=""
) as csv_file:
    pset_rows = list(csv.DictReader(csv_file))
```

Run scripts from the repository root so paths are stable:

```bash
python3 analysis/scripts/<script_name>.py
```

## Analysis conventions

- Treat source exports as immutable. Perform cleaning and normalization in code
  and write derived artifacts to a clearly named output directory.
- Preserve source problem and annotation IDs so every aggregate can be traced
  back to its input row.
- Record the input filename, row count, filters, and label mapping used by each
  generated report.
- Distinguish annotation rows from unique problems and unique reviewers when
  reporting counts.
- Define missing-value handling and any exclusion criteria in the analysis
  script, not through manual spreadsheet edits.
- Add focused `unittest` coverage for reusable parsing, normalization, and
  aggregation logic.

## Privacy

Some raw exports contain reviewer names or email addresses, timestamps, and
links to uploaded files. Do not reproduce personally identifying information in
logs, charts, reports, test fixtures, or model prompts. Aggregate or pseudonymize
reviewer-level results, and review derived artifacts before committing them.
