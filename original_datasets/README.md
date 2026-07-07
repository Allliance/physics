# Original Datasets

This directory contains two self-contained JSONL files with the upstream
Physics and FrontierPhysics problem records.

## Files

- `FrontierPhysics.jsonl`
- `Physics-TTT.jsonl`

## FrontierPhysics.jsonl

This file is a row-wise merge of the upstream FrontierPhysics JSONL shards from:

```text
/scratch/kf2365/PHYSICS-rl/data/FrontierPhysics/*.jsonl
```

Rows: 471.

Each row is a JSON object with the original FrontierPhysics fields plus
`source_file`:

```text
source_file, id, question, solution, final_answers, images, rubric
```

All 471 rows have a non-empty `rubric` field. The upstream shards contain some
repeated `id` values across different source files, so `source_file` is kept to
make each row traceable.

## Physics-TTT.jsonl

This file is the upstream Physics problem data with rubrics merged by `id`.

Problem source:

```text
/scratch/kf2365/PHYSICS-rl/rubrics/data/*.jsonl
```

Rubric source:

```text
/scratch/kf2365/PHYSICS-rl/rubrics/rubrics_dataset/all_with_rubrics_merged.json
```

Rows: 1297.

Each row is a JSON object with the original Physics problem fields plus
`source_file`, `domain`, `rubric`, and `rubric_provider`:

```text
source_file, domain, id, questions, solutions, final_answers, graphs, rubric, rubric_provider
```

All 1297 rows have a non-empty `rubric` field.

## Integrity

SHA-256 checksums are recorded in `SHA256SUMS`.
