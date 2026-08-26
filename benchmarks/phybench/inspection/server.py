#!/usr/bin/env python3
"""Local inspection UI for PHYBench Codex evaluation artifacts."""

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


APP_DIR = Path(__file__).resolve().parent
BENCHMARK_ROOT = APP_DIR.parent
STATIC_DIR = APP_DIR / "static"
DATASET_PATH = BENCHMARK_ROOT / "data" / "PHYBench-fullques_v1.json"
DEFAULT_ARTIFACT_DIR = (
    BENCHMARK_ROOT / "artifacts" / "gpt-5.6-sol-high-best-of-5"
)
ARTIFACT_DIR = DEFAULT_ARTIFACT_DIR


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


@lru_cache(maxsize=1)
def load_rows() -> tuple[dict, ...]:
    questions = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    audit_by_id = {
        item["id"]: item
        for item in read_jsonl(ARTIFACT_DIR / "final_equivalence_audit.jsonl")
    }
    diagnostics_by_id = {
        item["id"]: item
        for item in read_jsonl(ARTIFACT_DIR / "eed_false_negative_diagnostics.jsonl")
    }
    generations_by_round = {
        round_number: {
            item["id"]: item
            for item in read_jsonl(
                ARTIFACT_DIR / f"round-{round_number}" / "generations.jsonl"
            )
        }
        for round_number in range(1, 6)
    }
    scores_by_round = {
        round_number: {
            item["id"]: item
            for item in read_jsonl(
                ARTIFACT_DIR / f"round-{round_number}" / "scores.jsonl"
            )
        }
        for round_number in range(1, 6)
    }

    rows = []
    for question in questions:
        item_id = str(question["id"])
        attempts = []
        for round_number in range(1, 6):
            generation = generations_by_round[round_number].get(item_id)
            score = scores_by_round[round_number].get(item_id)
            if generation is None or score is None:
                continue
            attempts.append(
                {
                    "round": round_number,
                    "final_answer": generation.get("final_answer", ""),
                    "normalized_final_answer": score.get(
                        "normalized_final_answer", generation.get("final_answer", "")
                    ),
                    "eed_score": score.get("eed_score"),
                    "relative_distance": score.get("relative_distance"),
                    "tree_size": score.get("tree_size"),
                    "distance": score.get("distance"),
                    "success": bool(score.get("success")),
                    "usage": generation.get("usage") or {},
                    "created_at": generation.get("created_at", ""),
                }
            )
        best_eed = max(
            (float(attempt["eed_score"]) for attempt in attempts), default=None
        )
        solved_round = next(
            (attempt["round"] for attempt in attempts if attempt["success"]), None
        )
        audit = audit_by_id.get(item_id) or {
            "verdict": "NATIVE_SOLVED" if solved_round is not None else "NOT_REVIEWED",
            "reason": "Native EED found an exact symbolic match." if solved_round else "",
            "equivalent_rounds": [solved_round] if solved_round else [],
        }
        diagnostic = diagnostics_by_id.get(item_id) or {}
        rows.append(
            {
                "id": item_id,
                "tag": question.get("tag", ""),
                "question": question.get("content", ""),
                "solution": question.get("solution", ""),
                "reference_answer": question.get("answer", ""),
                "attempts": attempts,
                "attempt_count": len(attempts),
                "best_eed": best_eed,
                "round_1_eed": attempts[0]["eed_score"] if attempts else None,
                "solved": solved_round is not None,
                "solved_round": solved_round,
                "audit_verdict": audit["verdict"],
                "audit_reason": audit.get("reason", ""),
                "audit_equivalent_rounds": audit.get("equivalent_rounds", []),
                "eed_failure_stage": diagnostic.get("failure_stage", ""),
                "eed_diagnostic_exception": diagnostic.get("exception", ""),
            }
        )
    return tuple(rows)


def compact(value: str, limit: int = 300) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def summary(row: dict) -> dict:
    return {
        "id": row["id"],
        "tag": row["tag"],
        "question": compact(row["question"]),
        "attempt_count": row["attempt_count"],
        "best_eed": row["best_eed"],
        "round_1_eed": row["round_1_eed"],
        "solved": row["solved"],
        "solved_round": row["solved_round"],
        "audit_verdict": row["audit_verdict"],
    }


def filtered_rows(params: dict) -> list[dict]:
    phrase = params.get("q", [""])[0].casefold().strip()
    tag = params.get("tag", [""])[0].strip()
    status = params.get("status", ["all"])[0]
    score_sort = params.get("score_sort", [""])[0]
    audit = params.get("audit", [""])[0]
    if status not in {"all", "solved", "unsolved"}:
        raise ValueError("status must be all, solved, or unsolved")
    if score_sort not in {"", "asc", "desc"}:
        raise ValueError("score_sort must be asc, desc, or empty")
    valid_audits = {
        "", "NATIVE_SOLVED", "GRADER_FALSE_NEGATIVE", "REFERENCE_ANSWER_ISSUE",
        "MODEL_WRONG", "UNCERTAIN", "NOT_REVIEWED",
    }
    if audit not in valid_audits:
        raise ValueError("Unknown audit verdict")

    rows = list(load_rows())
    if phrase:
        rows = [
            row
            for row in rows
            if phrase in row["question"].casefold() or phrase in row["id"].casefold()
        ]
    if tag:
        rows = [row for row in rows if row["tag"] == tag]
    if status != "all":
        solved = status == "solved"
        rows = [row for row in rows if row["solved"] is solved]
    if audit:
        rows = [row for row in rows if row["audit_verdict"] == audit]
    if score_sort:
        rows.sort(
            key=lambda row: (
                row["best_eed"] is None,
                row["best_eed"] if score_sort == "asc" else -(row["best_eed"] or 0),
            )
        )
    return rows


class InspectionHandler(BaseHTTPRequestHandler):
    server_version = "PHYBenchInspection/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def send_json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        params = parse_qs(parsed.query)
        try:
            if path == "/api/meta":
                return self.handle_meta()
            if path == "/api/samples":
                return self.handle_samples(params)
            if path == "/api/sample":
                return self.handle_sample(params)
            return self.serve_static(path)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json(
                {"error": f"{type(exc).__name__}: {exc}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def handle_meta(self) -> None:
        rows = load_rows()
        solved = sum(row["solved"] for row in rows)
        tags = sorted({row["tag"] for row in rows})
        self.send_json(
            {
                "benchmark": "PHYBench",
                "artifact": str(ARTIFACT_DIR.relative_to(BENCHMARK_ROOT)),
                "total": len(rows),
                "solved": solved,
                "unsolved": len(rows) - solved,
                "tags": tags,
                "audit_counts": {
                    verdict: sum(row["audit_verdict"] == verdict for row in rows)
                    for verdict in sorted({row["audit_verdict"] for row in rows})
                },
            }
        )

    def handle_samples(self, params: dict) -> None:
        limit = max(1, min(200, int(params.get("limit", ["50"])[0])))
        offset = max(0, int(params.get("offset", ["0"])[0]))
        rows = filtered_rows(params)
        self.send_json(
            {
                "total": len(rows),
                "offset": offset,
                "limit": limit,
                "items": [summary(row) for row in rows[offset : offset + limit]],
            }
        )

    def handle_sample(self, params: dict) -> None:
        item_id = params.get("id", [""])[0]
        if not item_id:
            raise ValueError("Missing id")
        row = next((row for row in load_rows() if row["id"] == item_id), None)
        if row is None:
            raise ValueError(f"Unknown PHYBench id: {item_id}")
        self.send_json({"sample": row})

    def serve_static(self, path: str) -> None:
        if path in {"", "/"}:
            file_path = STATIC_DIR / "index.html"
        else:
            file_path = (STATIC_DIR / path.lstrip("/")).resolve()
            try:
                file_path.relative_to(STATIC_DIR)
            except ValueError:
                return self.send_json({"error": "Forbidden"}, HTTPStatus.FORBIDDEN)
        if not file_path.is_file():
            return self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type",
            mimetypes.guess_type(file_path.name)[0] or "application/octet-stream",
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    global ARTIFACT_DIR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("PHYBENCH_INSPECTION_PORT", 8766))
    )
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    args = parser.parse_args()
    ARTIFACT_DIR = args.artifact_dir.resolve()
    if not DATASET_PATH.is_file():
        parser.error(f"Dataset not found: {DATASET_PATH}")
    if not ARTIFACT_DIR.is_dir():
        parser.error(f"Artifact directory not found: {ARTIFACT_DIR}")
    load_rows.cache_clear()
    server = ThreadingHTTPServer((args.host, args.port), InspectionHandler)
    print(f"PHYBench inspection running at http://{args.host}:{args.port}")
    print(f"Artifacts: {ARTIFACT_DIR}")
    print("Press Ctrl-C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
