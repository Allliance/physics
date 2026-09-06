# Audit post-processing

Run from the repository root after updating `audits.csv` or the overrides:

```sh
python3 audit/scripts/process_audits.py
```

The script leaves `audits.csv` and `audit-overrides.json` unchanged and regenerates
`audit/audits_processed.csv` and `audit/conflicts.json`. It prints the number of
problems still needing manual review. Paths default to the `audit/` directory,
so it also works from other working directories. Custom paths can be supplied
with `--input`, `--output`, `--conflicts`, and `--overrides`.

The processed CSV drops the six fields `review_time_seconds`,
`review_timer_started_at`, `review_tracking_expected_at`, `reviewer_id`,
`assigned_at`, and `submitted_at`. Problems are grouped by `(dataset,
source_problem_id)` in first-occurrence order. Selection rules:

- A manual override always takes precedence, including for a lone audit,
  agreeing passes, or disagreements already resolved by pass 3.
- Matching pass 1 and pass 2 labels: keep the audit with the longest note.
  Pass 3 is only consulted when passes 1 and 2 disagree.
- Disagreeing pass 1 and pass 2 labels: if pass 3 matches either label, choose
  the longest note among the two matching audits.
- No matching pass 3: record a conflict and keep every pass in the processed
  CSV until an override resolves it.
- A lone audit is kept. If pass 1 or pass 2 is missing, available audits with
  matching labels are consolidated; disagreeing labels are flagged for review.

Note length is the number of characters, including whitespace. Equal lengths
are resolved by the first occurrence in the input CSV. Multiple audits for the
same problem and pass, or pass numbers outside 1–3, raise an error for inspection.

`conflicts.json` contains counts in `summary` and a `conflicts` list. Unresolved
problems come first, followed by problems resolved through overrides. Each entry
contains all original audits with the six excluded columns removed. Every applied
override appears as a resolved entry, even when the passes had no unresolved
disagreement; `summary.resolved_conflicts` counts all such overridden problems.
Automatically resolved pass 3 disagreements without an override do not appear here.

## Manual overrides

An absent or empty `audit-overrides.json` means no overrides. To set a manual
verdict, use a JSON list with one entry per problem, copying its dataset and
source problem ID from `audits.csv` or `conflicts.json`:

```json
[
  {
    "dataset": "hle-physics",
    "source_problem_id": "67370aa83f0517b6e8a60769",
    "label": "PROBLEM_FAILURE",
    "note": "Manual review: the reference answer is truncated."
  }
]
```

Allowed override labels are `PROBLEM_FAILURE`, `GRADER_FAILURE`, and
`MODEL_FAILURE`. `note` is optional. Overrides always set the processed verdict
for the matching `(dataset, source_problem_id)`, regardless of the pass labels
or number of audits. Only entries for problems absent from the current export
are ignored. Invalid input records still raise errors before output is written.

For an override, the script selects the longest original note with the chosen
label, using input order to break ties, then replaces its note if one is supplied.
If no audit has the chosen label, it uses the first audit's identifying fields
and an empty note unless the override supplies one. The retained `annotation_id`
and `pass` identify the original row used as a template. The conflict entry's
`override` and `resolved_audit` fields record the manual resolution explicitly.

Run the network-free tests with:

```sh
python3 -m unittest discover -s audit/tests -p 'test_*.py'
```

## Expert review PDF

Regenerate the conflicts after any audit or override updates, then build the report:

```sh
python3 audit/scripts/process_audits.py
python3 audit/scripts/build_conflict_report.py
```

The separate report script reads `audit/conflicts.json` and includes only entries
with `status: "unresolved"`. It writes `audit/reports/unresolved_conflicts.pdf`,
plus `.tex` source and a `.json` companion containing all source text and a mapping
from report question numbers (Q1, Q2, …) to dataset and source problem IDs. Question
numbers are assigned by numeric display ID and may change as conflicts are resolved;
use the companion JSON to match expert decisions to the correct override keys.

Each problem includes its question, reference solution, model response, every
human audit pass and note, the stored AI audit when available, scoring metadata,
and space for the expert's final label and explanation. Records are joined to
`audit/selected/*/responses.jsonl` by dataset and source problem ID. Missing or
duplicate response records raise errors rather than silently omitting problems.
An empty review queue produces a report stating that there are zero unresolved
problems.

The layout and math renderer are adapted from the original PSet disagreement
report and are self-contained under `audit/scripts/`. Stored mathematics is
typeset where possible. If a section contains invalid TeX, the script prints a
notice and preserves that section as wrapped source text; the JSON companion
lists these sections in `source_text_sections`. Failed builds leave existing
reports intact, and temporary LaTeX files are cleaned up automatically.

Python uses only the standard library. PDF generation requires `xelatex`, the
TeX packages used by the original report, and DejaVu fonts. On Debian/Ubuntu:

```sh
sudo apt-get install texlive-xetex texlive-latex-extra fonts-dejavu-core
```

Custom paths are supported from any working directory:

```sh
python3 audit/scripts/build_conflict_report.py \
  --conflicts audit/conflicts.json \
  --selected-dir audit/selected \
  --output audit/reports/unresolved_conflicts.pdf
```

The script uses the conflict statuses as supplied; it does not rerun audit
processing or read overrides itself. The generated reports can be reproduced
from the conflict file and selected response records.
