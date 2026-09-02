# Human annotation exports

`physics-audit-2026-09-02.csv` is a snapshot of the 285 submitted human
annotations from 12 reviewers in the Physics Annotation app as of 2026-09-02.
In-progress and deleted annotation records are not included, matching the app's
administrative CSV export behavior.

Join `display_id` to the `display_id` field in the JSONL files under
`audit/selected/`. The `dataset` and `source_problem_id` columns also identify
the original benchmark row through `audit/selected/id-mapping.json`.

Reviewer email addresses are replaced by stable IDs (`reviewer_001`, etc.) so
that repeated reviews by the same person can be analyzed without publishing
their identity. Free-text notes were checked for email addresses, reviewer
names, and phone-like strings before export; none were found.
