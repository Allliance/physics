# Messy Multi-Part Partitioning

This directory contains a small LLM pipeline for converting rows labeled
`messy_multi_part` into explicit clean multi-part question text.

The transformation is intentionally narrow: the LLM should only insert labels
such as `(a)`, `(b)`, `(c)` and line breaks. It should not change scientific
content.

## Smoke Test

```bash
rtk /home/alliiance/.local/bin/uv run --with pyarrow python3 data/partition/partition_messy_questions.py \
  --limit 5 \
  --workers 2 \
  --output scratch/multipart_analysis/messy_partition_smoke.jsonl \
  --review-md scratch/multipart_analysis/messy_partition_smoke_review.md \
  --model gpt-5.5 \
  --model-reasoning-effort high
```

## Verification

For every partitioned question, the script removes inserted line-start labels
like `(a)` and compares the original question to the partitioned question.

It records:

- `token_multiset_jaccard`: multiset token overlap after normalization.
- `missing_token_fraction`: fraction of original tokens missing from output.
- `added_token_fraction`: fraction of output tokens not present in original.
- `content_token_multiset_jaccard`: overlap after removing low-information
  connector words such as "the", "and", "find", and "following".
- `missing_content_token_fraction`: fraction of original significant tokens
  missing from output.
- `added_content_token_fraction`: fraction of output significant tokens not
  present in original.
- `length_ratio_without_labels`: normalized output/original character length.
- `part_labels` and whether they are consecutive from `(a)`.
- `new_doubled_latex_commands`: LaTeX commands that gained a doubled
  backslash in the output.

A row passes verification only if:

- at least two part labels are present;
- labels are consecutive from `(a)`;
- token multiset Jaccard is at least `0.80`;
- missing-token fraction is at most `0.12`;
- added-token fraction is at most `0.16`;
- content-token multiset Jaccard is at least `0.92`;
- missing content-token fraction is at most `0.06`;
- added content-token fraction is at most `0.08`;
- normalized length ratio is between `0.75` and `1.35`.
- no newly doubled LaTeX command backslashes are present.

These checks do not prove semantic identity, but they are designed to catch
large paraphrases, dropped scientific content, added scientific content, missing
labels, and malformed label sequences. The all-token metrics are still recorded
so connector-word churn remains visible during manual review.
