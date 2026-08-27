# Upstream provenance

This directory was imported from <https://github.com/kaiyuef/PHYSICS> at
commit `7d04146` (`translate`). The nested Git metadata was removed so the
benchmark is tracked as ordinary files in this repository.

`PHYSICS/PHYSICS-textonly/physics_textonly.jsonl` is a lossless concatenation
of the six subject-specific text-only JSONL files. Rebuild it with:

```bash
python3 aggregate_textonly.py
```
