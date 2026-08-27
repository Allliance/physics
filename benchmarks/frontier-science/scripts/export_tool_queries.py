#!/usr/bin/env python3
"""Export the web queries from the tool-enabled FrontierScience run."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "artifacts" / "gpt-5.6-sol-high-tools-on-five-round-failures"


def main() -> int:
    source = ARTIFACTS / "generations.jsonl"
    output = ARTIFACTS / "web_search_queries.jsonl"
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    exported = []
    for row in rows:
        queries = []
        for item in row.get("tool_items", []):
            if item.get("type") != "web_search":
                continue
            action = item.get("action") or {}
            if action.get("type") == "search":
                queries.extend(action.get("queries") or ([item["query"]] if item.get("query") else []))
        if queries:
            exported.append({"id": row["id"], "track": row["track"], "queries": queries})
    with output.open("w", encoding="utf-8") as handle:
        for row in exported:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {sum(len(row['queries']) for row in exported)} queries for {len(exported)} responses to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
