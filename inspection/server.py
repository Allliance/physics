#!/usr/bin/env python3
# /// script
# dependencies = ["pyarrow>=16"]
# ///
from __future__ import annotations

import argparse
import json
import mimetypes
import os
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pyarrow.parquet as pq


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
STATIC_DIR = APP_DIR / "static"


def rel(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT).as_posix()


def human_label(path: str) -> str:
    return path.replace("_", " ").replace("/", " / ")


def dataset_id(kind: str, path: str) -> str:
    return f"{kind}:{path}"


def parse_dataset_id(value: str) -> tuple[str, Path]:
    if ":" not in value:
        raise ValueError("Malformed dataset id")
    kind, raw_path = value.split(":", 1)
    path = (PROJECT_ROOT / raw_path).resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError("Dataset path escapes project root") from exc
    if kind not in {"parquet-file", "parquet-dir", "jsonl-file"}:
        raise ValueError(f"Unsupported dataset kind: {kind}")
    return kind, path


def discover_datasets() -> list[dict]:
    datasets: list[dict] = []

    parquet_roots = []
    filtered = PROJECT_ROOT / "filtered_datasets"
    if filtered.exists():
        for directory in sorted({p.parent.parent for p in filtered.glob("*/*/*/*.parquet")}):
            files = sorted(directory.glob("*/*.parquet"))
            if files:
                parquet_roots.append((directory, files))

    for directory, files in parquet_roots:
        relative = rel(directory)
        datasets.append(
            {
                "id": dataset_id("parquet-dir", relative),
                "label": f"{directory.name} - all prepared parts",
                "path": relative,
                "type": "parquet directory",
                "files": len(files),
            }
        )

    for parquet in sorted(filtered.glob("**/*.parquet")) if filtered.exists() else []:
        relative = rel(parquet)
        datasets.append(
            {
                "id": dataset_id("parquet-file", relative),
                "label": human_label(relative),
                "path": relative,
                "type": "parquet file",
                "files": 1,
            }
        )

    original = PROJECT_ROOT / "original_datasets"
    for jsonl in sorted(original.glob("*.jsonl")) if original.exists() else []:
        relative = rel(jsonl)
        datasets.append(
            {
                "id": dataset_id("jsonl-file", relative),
                "label": human_label(relative),
                "path": relative,
                "type": "jsonl file",
                "files": 1,
            }
        )

    return datasets


def safe_string(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def read_parquet_file(path: Path) -> list[dict]:
    table = pq.read_table(path)
    rows = table.to_pylist()
    for row in rows:
        row.setdefault("__dataset_file", rel(path))
        parent = path.parent.name
        if parent in {"train", "test", "validation", "val", "dev"}:
            row.setdefault("__split", parent)
            row.setdefault("__part", path.stem)
    return rows


def read_jsonl_file(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                row = {"__parse_error": str(exc), "__raw_line": line}
            row.setdefault("__dataset_file", rel(path))
            row.setdefault("__line_number", line_number)
            rows.append(row)
    return rows


@lru_cache(maxsize=32)
def load_dataset(dataset: str) -> tuple[dict, ...]:
    kind, path = parse_dataset_id(dataset)
    rows: list[dict] = []
    if kind == "parquet-dir":
        for parquet in sorted(path.glob("*/*.parquet")):
            rows.extend(read_parquet_file(parquet))
    elif kind == "parquet-file":
        rows.extend(read_parquet_file(path))
    elif kind == "jsonl-file":
        rows.extend(read_jsonl_file(path))

    normalized = []
    for index, row in enumerate(rows):
        item = dict(row)
        item["__row_index"] = index
        normalized.append(item)
    return tuple(normalized)


def question_text(row: dict) -> str:
    for key in ("question", "statement", "problem", "prompt"):
        if key in row:
            return safe_string(row[key])
    return ""


def label_values(row: dict) -> list[str]:
    values = []
    for key in ("label", "labels", "verdict", "part", "__part", "category", "split", "__split"):
        if key not in row or row[key] in (None, ""):
            continue
        value = row[key]
        if isinstance(value, list):
            values.extend(safe_string(item) for item in value if item not in (None, ""))
        else:
            values.append(safe_string(value))
    return [value for value in dict.fromkeys(values) if value]


def label_options(rows: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for row in rows:
        for value in label_values(row):
            counts[value] = counts.get(value, 0) + 1
    return [{"value": key, "count": counts[key]} for key in sorted(counts, key=str.casefold)]


def compact(text: str, limit: int = 260) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def sample_summary(row: dict) -> dict:
    question = question_text(row)
    return {
        "row_index": row["__row_index"],
        "id": safe_string(row.get("id") or row.get("sample_id") or row.get("__line_number") or row["__row_index"]),
        "question": compact(question),
        "question_length": len(question),
        "source_file": safe_string(row.get("source_file") or row.get("__dataset_file")),
        "split": safe_string(row.get("__split") or row.get("split")),
        "part": safe_string(row.get("__part") or row.get("verdict") or row.get("part")),
        "labels": label_values(row),
        "field_count": len([key for key in row if not key.startswith("__")]),
    }


def filtered_rows(dataset: str, phrase: str, label: str = "") -> list[dict]:
    rows = list(load_dataset(dataset))
    phrase = phrase.casefold().strip()
    label = label.strip()
    if phrase:
        rows = [row for row in rows if phrase in question_text(row).casefold()]
    if label:
        rows = [row for row in rows if label in label_values(row)]
    return rows


class InspectionHandler(BaseHTTPRequestHandler):
    server_version = "InspectionTool/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def send_json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"error": message}, status)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        params = parse_qs(parsed.query)

        try:
            if path == "/api/datasets":
                return self.send_json({"datasets": discover_datasets()})
            if path == "/api/samples":
                return self.handle_samples(params)
            if path == "/api/sample":
                return self.handle_sample(params)
            return self.serve_static(path)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
        except FileNotFoundError as exc:
            self.send_error_json(HTTPStatus.NOT_FOUND, str(exc))
        except Exception as exc:  # Keep UI failures readable during local inspection.
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

    def handle_samples(self, params: dict) -> None:
        dataset = params.get("dataset", [""])[0]
        if not dataset:
            raise ValueError("Missing dataset")
        phrase = params.get("q", [""])[0]
        label = params.get("label", [""])[0]
        limit = max(1, min(200, int(params.get("limit", ["50"])[0])))
        offset = max(0, int(params.get("offset", ["0"])[0]))

        all_rows = list(load_dataset(dataset))
        rows = filtered_rows(dataset, phrase, label)
        page = rows[offset : offset + limit]
        fields = sorted({key for row in rows[:200] for key in row if not key.startswith("__")})
        self.send_json(
            {
                "total": len(rows),
                "offset": offset,
                "limit": limit,
                "items": [sample_summary(row) for row in page],
                "fields": fields,
                "label_options": label_options(all_rows),
            }
        )

    def handle_sample(self, params: dict) -> None:
        dataset = params.get("dataset", [""])[0]
        row_index_raw = params.get("row_index", [""])[0]
        if not dataset or row_index_raw == "":
            raise ValueError("Missing dataset or row_index")
        row_index = int(row_index_raw)
        rows = load_dataset(dataset)
        if row_index < 0 or row_index >= len(rows):
            raise ValueError("row_index is out of range")
        row = rows[row_index]
        visible_fields = {key: value for key, value in row.items() if key != "__row_index"}
        self.send_json({"sample": visible_fields})

    def serve_static(self, path: str) -> None:
        if path in {"", "/"}:
            file_path = STATIC_DIR / "index.html"
        else:
            file_path = (STATIC_DIR / path.lstrip("/")).resolve()
            try:
                file_path.relative_to(STATIC_DIR)
            except ValueError:
                self.send_error_json(HTTPStatus.FORBIDDEN, "Forbidden")
                return

        if not file_path.exists() or not file_path.is_file():
            self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")
            return

        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local dataset inspection web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=int(os.environ.get("INSPECTION_PORT", 8765)), type=int)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), InspectionHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"Inspection tool running at {url}")
    print("Press Ctrl-C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
