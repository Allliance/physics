# Audit post-processing

Run from the repository root after updating `audits.csv` or the overrides:

```sh
python3 audit/process_audits.py
```

The script leaves `audits.csv` and `audit-overrides.json` unchanged and regenerates
`audit/audits_processed.csv` and `audit/conflicts.json`. It prints the number of
problems still needing manual review. Paths default to the script's directory,
so it also works from other working directories. Custom paths can be supplied
with `--input`, `--output`, `--conflicts`, and `--overrides`.

The processed CSV drops the six fields `review_time_seconds`,
`review_timer_started_at`, `review_tracking_expected_at`, `reviewer_id`,
`assigned_at`, and `submitted_at`. Problems are grouped by `(dataset,
source_problem_id)` in first-occurrence order. Selection rules:

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
contains all original audits with the six excluded columns removed. Automatically
resolved pass 3 disagreements are not manual conflicts and do not appear here.

## Manual overrides

An absent or empty `audit-overrides.json` means no overrides. To resolve a
conflict, use a JSON list with one entry per problem, copying its dataset and
source problem ID from `conflicts.json`:

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
`MODEL_FAILURE`. `note` is optional. Overrides apply only to manual conflicts.
An entry for a problem absent from the current export or already resolved by
the pass rules is ignored.

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
