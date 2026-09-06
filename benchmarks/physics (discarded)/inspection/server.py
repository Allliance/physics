#!/usr/bin/env python3
# /// script
# dependencies = ["pyarrow>=16"]
# ///
from __future__ import annotations

import argparse
import hashlib
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
SPLIT_NAMES = {"train", "test", "validation", "val", "dev"}
ORIGINAL_DATASET_DIRS = (
    PROJECT_ROOT / "original_datasets",
    PROJECT_ROOT / "backup" / "0_original_datasets",
)
VISIBLE_DATASET_PATHS = {
    "final_datasets/hardest_filtered_full.parquet",
    "inspection/reviews/hardest_filtered_gpt55_best_of_4.json",
}
HARD_FILTERED_FULL_PATH = "final_datasets/hardest_filtered_full.parquet"
HARD_FILTERED_FULL_EVAL_DIR = (
    PROJECT_ROOT
    / "eval"
    / "artifacts"
    / "final_datasets"
    / "hardest_filtered_full"
    / "merged"
    / "model_gpt-5.5_gen_f2a55bc001"
)


def rel(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT).as_posix()


def human_label(path: str) -> str:
    return path.replace("_", " ").replace("/", " / ")


def dataset_id(kind: str, path: str) -> str:
    return f"{kind}:{path}"


def unique_existing_dirs(paths: tuple[Path, ...]) -> list[Path]:
    seen: set[Path] = set()
    existing = []
    for path in paths:
        if not path.exists():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        existing.append(path)
    return existing


def review_metadata(review: Path) -> tuple[str, str]:
    if review.name == "original_test_ground_truth_extraction_issues.json":
        return "Original test sets / ground-truth extraction issues", "ground-truth extraction issues"
    return f"Evaluation review / {review.stem.replace('_', ' ')}", "evaluation review"


def parse_dataset_id(value: str) -> tuple[str, Path]:
    if ":" not in value:
        raise ValueError("Malformed dataset id")
    kind, raw_path = value.split(":", 1)
    path = (PROJECT_ROOT / raw_path).resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError("Dataset path escapes project root") from exc
    if kind not in {"parquet-file", "parquet-dir", "jsonl-file", "json-file", "repair-file"}:
        raise ValueError(f"Unsupported dataset kind: {kind}")
    return kind, path


def discover_datasets() -> list[dict]:
    datasets: list[dict] = []

    review_dir = PROJECT_ROOT / "inspection" / "reviews"
    for review in sorted(review_dir.glob("*.json")) if review_dir.exists() else []:
        relative = rel(review)
        label, kind = review_metadata(review)
        datasets.append(
            {
                "id": dataset_id("json-file", relative),
                "label": label,
                "path": relative,
                "type": kind,
                "files": 1,
            }
        )

    ground_truth_outputs = PROJECT_ROOT / "data" / "extract_gt" / "outputs"
    ground_truth_files = (
        sorted(ground_truth_outputs.glob("dev_set*/*.parquet"))
        if ground_truth_outputs.exists()
        else []
    )
    for parquet in ground_truth_files:
        relative = rel(parquet)
        datasets.append(
            {
                "id": dataset_id("parquet-file", relative),
                "label": f"Extracted ground truths / {parquet.parent.name} / {parquet.stem}",
                "path": relative,
                "type": "ground-truth extraction",
                "files": 1,
            }
        )

    parquet_roots = []
    filtered = PROJECT_ROOT / "filtered_datasets"
    if filtered.exists():
        candidates = {p.parent.parent for p in filtered.glob("**/*.parquet") if p.parent.name in SPLIT_NAMES}
        for directory in sorted(candidates):
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

    repaired = PROJECT_ROOT / "repaired_datasets"
    repaired_roots = []
    if repaired.exists():
        for directory in sorted({p.parent for p in repaired.glob("*/*.parquet")}):
            files = sorted(directory.glob("*.parquet"))
            if files:
                repaired_roots.append((directory, files))

    for directory, files in repaired_roots:
        relative = rel(directory)
        datasets.append(
            {
                "id": dataset_id("parquet-dir", relative),
                "label": f"{directory.name} - all repaired parts",
                "path": relative,
                "type": "repaired parquet directory",
                "files": len(files),
            }
        )

    parquet_files = []
    for root in (filtered, repaired):
        if root.exists():
            parquet_files.extend(root.glob("**/*.parquet"))

    for parquet in sorted(parquet_files):
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

    final_datasets = PROJECT_ROOT / "final_datasets"
    for parquet in sorted(final_datasets.glob("*.parquet")) if final_datasets.exists() else []:
        relative = rel(parquet)
        datasets.append(
            {
                "id": dataset_id("parquet-file", relative),
                "label": f"Final dataset / {parquet.stem.replace('_', ' ')}",
                "path": relative,
                "type": "final dataset",
                "files": 1,
            }
        )

    for original in unique_existing_dirs(ORIGINAL_DATASET_DIRS):
        for parquet in sorted(original.glob("prepared/*/test.parquet")):
            relative = rel(parquet)
            datasets.append(
                {
                    "id": dataset_id("parquet-file", relative),
                    "label": f"Original test set / {parquet.parent.name}",
                    "path": relative,
                    "type": "original test set",
                    "files": 1,
                }
            )

    repair_dev_set = PROJECT_ROOT / "data" / "repair" / "dev_set"
    for repaired in sorted(repair_dev_set.glob("*_repaired.json")) if repair_dev_set.exists() else []:
        original_path = repaired.with_name(repaired.name.replace("_repaired.json", ".json"))
        relative = rel(repaired)
        datasets.append(
            {
                "id": dataset_id("repair-file", relative),
                "label": f"Repair / dev_set / {original_path.stem}",
                "path": relative,
                "type": "repair comparison",
                "files": 2 if original_path.exists() else 1,
            }
        )

    return [dataset for dataset in datasets if dataset["path"] in VISIBLE_DATASET_PATHS]


def safe_string(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def eval_row_key(dataset: Path, row: dict) -> str:
    identity = f"{dataset.resolve()}\0{row.get('id')}\0{row.get('question')}"
    return hashlib.sha256(identity.encode()).hexdigest()[:20]


def read_keyed_jsonl(path: Path, key: str = "key") -> dict[str, dict]:
    if not path.exists():
        return {}
    rows = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            rows[item[key]] = item
    return rows


@lru_cache(maxsize=4)
def hard_filtered_full_eval_records() -> tuple[dict[str, dict], dict[str, dict]]:
    responses = read_keyed_jsonl(HARD_FILTERED_FULL_EVAL_DIR / "responses.jsonl")
    judgments = read_keyed_jsonl(HARD_FILTERED_FULL_EVAL_DIR / "judge_gpt-5.5" / "judgments.jsonl")
    return responses, judgments


def enrich_hard_filtered_full_eval(path: Path, row: dict) -> dict:
    if rel(path) != HARD_FILTERED_FULL_PATH:
        return row
    responses, judgments = hard_filtered_full_eval_records()
    key = eval_row_key(path, row)
    response = responses.get(key)
    judgment = judgments.get(key)
    if response is None and judgment is None:
        return row

    item = dict(row)
    item["latest_eval_key"] = key
    item["latest_eval_artifact"] = rel(HARD_FILTERED_FULL_EVAL_DIR / "judge_gpt-5.5")
    item["latest_eval_model"] = "gpt-5.5 high"
    item["latest_eval_mode"] = "merged"
    if response is not None:
        item["latest_model_response"] = response.get("response") or ""
        item["latest_extracted_answer"] = response.get("extracted_answer") or ""
        item["latest_format_errors"] = response.get("format_errors") or []
        item["latest_response_usage"] = response.get("usage") or {}
    if judgment is not None:
        parts = []
        for part_id, part in (judgment.get("parts") or {}).items():
            if not isinstance(part, dict):
                continue
            parts.append(
                {
                    "part": part_id,
                    "score": part.get("score"),
                    "reason": part.get("reason", ""),
                }
            )
        item["latest_judge_score"] = judgment.get("score")
        item["latest_judge_parts"] = parts
        item["latest_judge_response"] = judgment.get("judge_response") or ""
        item["latest_judge_usage"] = judgment.get("usage") or {}
    return item


def read_parquet_file(path: Path) -> list[dict]:
    table = pq.read_table(path)
    rows = table.to_pylist()
    for row in rows:
        row.setdefault("__dataset_file", rel(path))
        parent = path.parent.name
        if parent in SPLIT_NAMES:
            row.setdefault("__split", parent)
            row.setdefault("__part", path.stem)
        elif path.stem in SPLIT_NAMES:
            row.setdefault("__split", path.stem)
            row.setdefault("__part", path.stem)
        row.update(enrich_hard_filtered_full_eval(path, row))
    return rows


def safe_project_path(raw_path: str) -> Path:
    path = (PROJECT_ROOT / raw_path).resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError("Source path escapes project root") from exc
    return path


@lru_cache(maxsize=32)
def read_parquet_rows(path_text: str) -> tuple[dict, ...]:
    return tuple(read_parquet_file(safe_project_path(path_text)))


def enrich_original_test_issue_row(row: dict) -> dict:
    path_text = row.get("source_dataset_file")
    row_index = row.get("original_row_index")
    if not path_text or row_index is None:
        return row

    source_rows = read_parquet_rows(safe_string(path_text))
    source_index = int(row_index)
    if source_index < 0 or source_index >= len(source_rows):
        return row

    source = source_rows[source_index]
    item = dict(row)
    item.setdefault("solution", source.get("solution") or source.get("solutions") or "")
    item.setdefault("source_file", source.get("source_file") or source.get("__dataset_file") or "")
    item.setdefault("question", source.get("question") or source.get("questions") or item.get("question", ""))
    item.setdefault("__split", source.get("__split") or "test")
    item.setdefault("__part", "ground-truth issue")
    return item


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


def read_json_file(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = [payload]
    else:
        raise ValueError(f"Unsupported JSON payload in {rel(path)}")

    normalized = []
    for row in rows:
        item = row if isinstance(row, dict) else {"value": row}
        item = enrich_original_test_issue_row(item)
        item.setdefault("__dataset_file", rel(path))
        normalized.append(item)
    return normalized


def read_json_rows(path: Path) -> list[dict]:
    try:
        return read_json_file(path)
    except json.JSONDecodeError:
        return read_jsonl_file(path)


def read_repair_file(path: Path) -> list[dict]:
    repaired_rows = read_json_rows(path)
    original_path = path.with_name(path.name.replace("_repaired.json", ".json"))
    original_by_id = {}
    if original_path.exists():
        for row in read_json_rows(original_path):
            row_id = safe_string(row.get("id"))
            if row_id:
                original_by_id[row_id] = row

    rows = []
    for row in repaired_rows:
        item = dict(row)
        row_id = safe_string(item.get("id"))
        original = original_by_id.get(row_id)
        if original and "question" in original:
            item["original_question"] = original["question"]
        else:
            item["original_question"] = item.get("question", "")
        if "repaired_question" not in item:
            item["repaired_question"] = item.get("question", "")
        item["question"] = item["original_question"]
        item.setdefault("repair_status", "repaired")
        item.setdefault("__dataset_file", rel(path))
        item.setdefault("__part", "repair")
        rows.append(item)
    return rows


@lru_cache(maxsize=32)
def load_dataset(dataset: str) -> tuple[dict, ...]:
    kind, path = parse_dataset_id(dataset)
    rows: list[dict] = []
    if kind == "parquet-dir":
        parquet_paths = sorted({*path.glob("*.parquet"), *path.glob("*/*.parquet")})
        for parquet in parquet_paths:
            rows.extend(read_parquet_file(parquet))
    elif kind == "parquet-file":
        rows.extend(read_parquet_file(path))
    elif kind == "jsonl-file":
        rows.extend(read_jsonl_file(path))
    elif kind == "json-file":
        rows.extend(read_json_file(path))
    elif kind == "repair-file":
        rows.extend(read_repair_file(path))

    normalized = []
    for index, row in enumerate(rows):
        item = dict(row)
        item["__row_index"] = index
        normalized.append(item)
    return tuple(normalized)


def question_text(row: dict) -> str:
    for key in ("question", "questions", "statement", "problem", "prompt"):
        if key in row:
            return safe_string(row[key])
    return ""


def label_values(row: dict) -> list[str]:
    values = []
    for key in ("label", "labels", "verdict", "part", "__part", "repair_status", "selection", "dataset", "category", "domain", "split", "__split"):
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


def first_value(row: dict, keys: tuple[str, ...]):
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def count_ground_truths(value) -> int:
    if value in (None, ""):
        return 0
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return 1 if value.strip() else 0
    if isinstance(parsed, list):
        return len(parsed)
    if isinstance(parsed, dict):
        return len(parsed)
    return 1


def row_score(row: dict):
    for key in ("latest_judge_score", "model_score", "score"):
        value = row.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def sort_rows_by_score(rows: list[dict], direction: str) -> list[dict]:
    if direction not in {"asc", "desc"}:
        return rows

    def sort_key(row: dict):
        score = row_score(row)
        if score is None:
            return (1, 0.0)
        return (0, score if direction == "asc" else -score)

    return sorted(rows, key=sort_key)


def compact(text: str, limit: int = 260) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def sample_summary(row: dict) -> dict:
    question = question_text(row)
    solution = first_value(row, ("solution", "solutions", "answer", "explanation"))
    ground_truths = first_value(row, ("ground_truths", "ground_truth", "final_answers", "answers"))
    return {
        "row_index": row["__row_index"],
        "id": safe_string(row.get("id") or row.get("sample_id") or row.get("__line_number") or row["__row_index"]),
        "question": compact(question),
        "question_length": len(question),
        "source_file": safe_string(row.get("source_file") or row.get("__dataset_file")),
        "split": safe_string(row.get("__split") or row.get("split")),
        "part": safe_string(row.get("__part") or row.get("verdict") or row.get("part")),
        "labels": label_values(row),
        "score": row_score(row),
        "has_solution": bool(safe_string(solution).strip()),
        "ground_truth_count": count_ground_truths(ground_truths),
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
        score_sort = params.get("score_sort", [""])[0]
        if score_sort not in {"", "asc", "desc"}:
            raise ValueError("score_sort must be asc, desc, or empty")
        limit = max(1, min(200, int(params.get("limit", ["50"])[0])))
        offset = max(0, int(params.get("offset", ["0"])[0]))

        all_rows = list(load_dataset(dataset))
        rows = filtered_rows(dataset, phrase, label)
        rows = sort_rows_by_score(rows, score_sort)
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
