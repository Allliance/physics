# ScalePhysics

ScalePhysics is the English-language subset of the upstream `desimfj/PHYSICS`
test split used by this repository's evaluation pipeline.

The prepared dataset is stored at `data/test.parquet`. Rebuild it from the
upstream dataset with:

```bash
python benchmarks/scale-physics/prepare.py
```

Run a one-row evaluation in merged mode with:

```bash
python -m eval ScalePhysics test --mode merged --limit 1
```
