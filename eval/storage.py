"""Content-addressed inputs and atomic checkpoints."""

import hashlib
import json
from pathlib import Path
import tempfile


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rows(path):
    path = Path(path)
    if path.suffix == '.parquet':
        import pyarrow.parquet as pq
        rows = pq.read_table(path).to_pylist()
    elif path.suffix == '.json':
        rows = json.loads(path.read_text())
    else:
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f'{path}: expected a list of objects')
    return rows


def atomic_json(path, value):
    path = Path(path)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write('\n')
            handle.flush()
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    temporary.replace(path)


def require_checkpoint(path, expected):
    if path.exists():
        if json.loads(path.read_text()) != expected:
            raise ValueError(f'Inputs/configuration changed: choose a new output directory ({path})')
    else:
        atomic_json(path, expected)
