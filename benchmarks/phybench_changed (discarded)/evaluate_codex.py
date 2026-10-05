#!/usr/bin/env python3
"""Evaluate a Codex CLI model on answer-bearing, text-only PHYBench rows."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BENCHMARK_ROOT = Path(__file__).resolve().parent
REPO_ROOT = BENCHMARK_ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(BENCHMARK_ROOT / "EED"))

from EED import EED  # noqa: E402
from utils.codex_cli import CodexLLM  # noqa: E402


DATASET_REVISION = "0da5232022d6036ec3ff63e031e3afd9f998f5a1"
DATASET_SHA256 = "a01955ffb2ff86d7833770d3d9f308e3bc1b0e2fea92c5092c4e68a619048a6b"
DATASET_PATH = BENCHMARK_ROOT / "data" / "PHYBench-fullques_v1.json"
ANSWER_SCHEMA = BENCHMARK_ROOT / ".answer-schema.json"
SYSTEM_PROMPT = """Solve the supplied physics problem yourself without tools, files, web search, or external context.
Return only the final symbolic answer requested by the problem. Do not include a derivation, explanation,
units unless the problem requests them, or surrounding prose. Use LaTeX notation."""
SCHEMA = {
    "type": "object",
    "properties": {"final_answer": {"type": "string"}},
    "required": ["final_answer"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Config:
    model: str
    reasoning_effort: str
    timeout: float
    rounds: int


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_jsonl(path: Path, item: dict[str, Any], lock: threading.Lock) -> None:
    with lock, path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        handle.flush()


def load_rows(limit: int | None = None) -> list[dict[str, Any]]:
    rows = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    rows = [row for row in rows if row.get("content") and row.get("answer")]
    if limit is not None:
        rows = rows[:limit]
    return rows


def generate(row: dict[str, Any], config: Config) -> dict[str, Any]:
    result = CodexLLM(
        model=config.model,
        model_reasoning_effort=config.reasoning_effort,
        timeout=config.timeout,
    ).complete(row["content"], system_prompt=SYSTEM_PROMPT, output_schema=ANSWER_SCHEMA)
    parsed = json.loads(result.text)
    return {
        "id": str(row["id"]),
        "tag": row["tag"],
        "final_answer": parsed["final_answer"],
        "usage": result.usage,
        "wrapper_attempts": result.attempts,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def normalize_latex(value: str) -> str:
    """Remove presentation-only syntax unsupported by the released EED parser."""
    value = value.strip()
    for opening, closing in (("\\[", "\\]"), ("$$", "$$"), ("$", "$")):
        if value.startswith(opening) and value.endswith(closing):
            value = value[len(opening) : len(value) - len(closing)].strip()
            break
    return value.replace("\\left", "").replace("\\right", "").strip()


def score(row: dict[str, Any], generation: dict[str, Any]) -> dict[str, Any]:
    normalized_answer = normalize_latex(generation["final_answer"])
    eed_score, relative_distance, tree_size, distance = EED(
        row["answer"], normalized_answer
    )
    return {
        "id": str(row["id"]),
        "tag": row["tag"],
        "reference_answer": row["answer"],
        "final_answer": generation["final_answer"],
        "normalized_final_answer": normalized_answer,
        "eed_score": float(eed_score),
        "relative_distance": float(relative_distance),
        "tree_size": float(tree_size),
        "distance": float(distance),
        "success": bool(eed_score == 100),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def summarize(output_root: Path, rows: list[dict[str, Any]], config: Config) -> dict[str, Any]:
    attempts: dict[str, list[dict[str, Any]]] = {str(row["id"]): [] for row in rows}
    solved_by_round: dict[str, int] = {}
    for round_number in range(1, config.rounds + 1):
        for item in read_jsonl(output_root / f"round-{round_number}" / "scores.jsonl"):
            if item["id"] in attempts:
                attempts[item["id"]].append({"round": round_number, **item})
        solved_by_round[str(round_number)] = sum(
            any(item["success"] for item in values) for values in attempts.values()
        )
    solved = {item_id for item_id, values in attempts.items() if any(v["success"] for v in values)}
    by_tag: dict[str, dict[str, int | float]] = {}
    for tag in sorted({row["tag"] for row in rows}):
        ids = {str(row["id"]) for row in rows if row["tag"] == tag}
        tag_solved = len(ids & solved)
        by_tag[tag] = {
            "total": len(ids),
            "solved": tag_solved,
            "pass_at_5": tag_solved / len(ids),
        }
    return {
        "benchmark": "Eureka-Lab/PHYBench text-only answer-bearing split",
        "dataset_revision": DATASET_REVISION,
        "dataset_sha256": DATASET_SHA256,
        "config": asdict(config),
        "evaluation": "Authors' EED implementation; success iff final-answer EED score == 100.",
        "retry_policy": "Up to five sequential trials; a problem is excluded after its first success.",
        "total": len(rows),
        "solved": len(solved),
        "pass_at_5": len(solved) / len(rows),
        "solved_cumulatively_by_round": solved_by_round,
        "by_tag": by_tag,
        "unsolved_ids": sorted(set(attempts) - solved, key=int),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=BENCHMARK_ROOT / "artifacts" / "gpt-5.6-sol-high-best-of-5",
    )
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds must be at least 1")
    ANSWER_SCHEMA.write_text(json.dumps(SCHEMA), encoding="utf-8")
    config = Config(args.model, args.reasoning_effort, args.timeout, args.rounds)
    rows = load_rows(args.limit)
    row_by_id = {str(row["id"]): row for row in rows}
    args.output_root.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    solved: set[str] = set()

    for round_number in range(1, args.rounds + 1):
        round_dir = args.output_root / f"round-{round_number}"
        round_dir.mkdir(exist_ok=True)
        generation_path = round_dir / "generations.jsonl"
        score_path = round_dir / "scores.jsonl"
        existing_generations = {item["id"]: item for item in read_jsonl(generation_path)}
        existing_scores = {item["id"]: item for item in read_jsonl(score_path)}
        solved.update(item["id"] for item in existing_scores.values() if item["success"])
        pending = [row for row in rows if str(row["id"]) not in solved]
        selection = {
            "round": round_number,
            "input_count": len(pending),
            "excluded_prior_successes": len(rows) - len(pending),
            "input_ids": [str(row["id"]) for row in pending],
        }
        (round_dir / "selection.json").write_text(
            json.dumps(selection, indent=2) + "\n", encoding="utf-8"
        )
        print(f"round {round_number}: evaluating {len(pending)} problems", flush=True)

        missing = [row for row in pending if str(row["id"]) not in existing_generations]
        with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
            futures = {pool.submit(generate, row, config): str(row["id"]) for row in missing}
            for future in as_completed(futures):
                item = future.result()
                existing_generations[item["id"]] = item
                write_jsonl(generation_path, item, lock)
                print(f"round {round_number} generated {item['id']}", flush=True)

        for row in pending:
            item_id = str(row["id"])
            if item_id in existing_scores:
                continue
            item = score(row, existing_generations[item_id])
            existing_scores[item_id] = item
            write_jsonl(score_path, item, lock)
            print(
                f"round {round_number} scored {item_id}: {item['eed_score']:.6g}",
                flush=True,
            )
        solved.update(item["id"] for item in existing_scores.values() if item["success"])
        summary = summarize(args.output_root, rows, config)
        (args.output_root / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        print(
            f"round {round_number} cumulative: {summary['solved']}/{summary['total']}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
