#!/usr/bin/env python3
"""Download the latest CMT dataset. Run with: python3 update_cmt_data.py."""

import json
from pathlib import Path
import tempfile
from urllib.error import URLError
from urllib.request import urlopen


SOURCE_URL = (
    "https://raw.githubusercontent.com/haoran0115/cmt-bench-sol/"
    "main/data/clean/cmt_data_clean.json"
)
DESTINATION = Path(__file__).resolve().parent / "data" / "cmt_data_clean.json"


def main():
    temporary_path = None
    try:
        with urlopen(SOURCE_URL, timeout=60) as response:
            data = response.read()
        json.loads(data)  # Validate before replacing the existing dataset.
        with tempfile.NamedTemporaryFile(
            dir=DESTINATION.parent, prefix=".cmt_data_clean.", delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(data)
        if DESTINATION.exists():
            temporary_path.chmod(DESTINATION.stat().st_mode & 0o777)
        temporary_path.replace(DESTINATION)
    except (URLError, OSError, ValueError) as error:
        raise SystemExit(f"Update failed: {error}") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    print(f"Updated {DESTINATION} ({len(data):,} bytes)")


if __name__ == "__main__":
    main()
