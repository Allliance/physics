"""Aggregate the six PHYSICS text-only subject files into one JSONL file."""

from __future__ import annotations

import json
from pathlib import Path


SUBJECTS = (
    "atomic",
    "electro",
    "mechanics",
    "optics",
    "quantum",
    "statistics",
)


def aggregate_textonly() -> Path:
    dataset_dir = Path(__file__).parent / "PHYSICS" / "PHYSICS-textonly"
    output_path = dataset_dir / "physics_textonly.jsonl"
    rows: list[str] = []
    seen_ids: set[str] = set()

    for subject in SUBJECTS:
        input_path = dataset_dir / f"{subject}_dataset_textonly.jsonl"
        for line_number, line in enumerate(
            input_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            row = json.loads(line)
            row_id = row.get("id")
            if not isinstance(row_id, str) or not row_id:
                raise ValueError(f"Missing id in {input_path}:{line_number}")
            if row_id in seen_ids:
                raise ValueError(f"Duplicate id {row_id!r} in {input_path}:{line_number}")
            if row.get("graphs") not in (None, []):
                raise ValueError(f"Non-text-only row {row_id!r} in {input_path}")
            seen_ids.add(row_id)
            rows.append(line)

    output_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} rows to {output_path}")
    return output_path


if __name__ == "__main__":
    aggregate_textonly()
