"""Read frozen native HLE inputs without accessing the Hub."""

import json
from pathlib import Path


def load_local_rows(path: Path) -> list[dict]:
    rows = ([json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            if path.suffix == ".jsonl" else json.loads(path.read_text()))
    if not isinstance(rows, list) or not rows:
        raise ValueError("HLE input must contain a nonempty list of rows")
    seen = set()
    for row in rows:
        for key in ("id", "question", "answer", "category"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"HLE row requires nonempty {key}")
        if row["id"] in seen:
            raise ValueError(f"Duplicate HLE ID: {row['id']}")
        seen.add(row["id"])
    return rows
