"""Download the ScalePhysics source and create its English-only evaluation parquet."""

from __future__ import annotations

import argparse
from pathlib import Path


REPOSITORY = "desimfj/PHYSICS"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "data/test.parquet"
REQUIRED_COLUMNS = {"id", "question", "solution", "language"}


def prepare(output: Path) -> tuple[int, int]:
    from datasets import load_dataset

    dataset = load_dataset(REPOSITORY, split="test")
    missing = REQUIRED_COLUMNS.difference(dataset.column_names)
    if missing:
        raise ValueError(f"{REPOSITORY} is missing required columns: {sorted(missing)}")

    english = dataset.filter(lambda row: row["language"] == "en")
    if any(language != "en" for language in english["language"]):
        raise ValueError("language filter left non-English samples in the output")
    if len(set(english["id"])) != len(english):
        raise ValueError("English sample IDs are not unique")

    output.parent.mkdir(parents=True, exist_ok=True)
    english.to_parquet(output)
    return len(dataset), len(english)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    total, kept = prepare(args.output)
    print(f"Wrote {kept}/{total} English rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
