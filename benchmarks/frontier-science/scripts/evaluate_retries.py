#!/usr/bin/env python3
"""Run sequential FrontierScience retries, dropping successes after each round."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BENCHMARK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCHMARK_ROOT))

import evaluate


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def successful_ids(judgments: list[dict[str, Any]]) -> set[str]:
    return {item["id"] for item in judgments if item["success"]}


def cumulative_summary(round_root: Path, rounds: int, config: evaluate.Config) -> dict[str, Any]:
    attempts: dict[str, list[dict[str, Any]]] = {}
    for round_number in range(1, rounds + 1):
        for item in read_jsonl(round_root / f"round-{round_number}" / "judgments.jsonl"):
            attempts.setdefault(item["id"], []).append({"round": round_number, **item})
    tracks: dict[str, Any] = {}
    for track, expected in (("olympiad", 50), ("research", 20)):
        track_attempts = {key: values for key, values in attempts.items() if values[0]["track"] == track}
        solved = {key for key, values in track_attempts.items() if any(value["success"] for value in values)}
        solved_by_round = {
            str(round_number): sum(
                any(value["success"] and value["round"] <= round_number for value in values)
                for values in track_attempts.values()
            )
            for round_number in range(1, rounds + 1)
        }
        tracks[track] = {
            "expected": expected,
            "solved": len(solved),
            "pass_at_5": len(solved) / expected,
            "solved_cumulatively_by_round": solved_by_round,
            "unsolved_ids": sorted(set(track_attempts) - solved),
        }
    return {
        "benchmark": "openai/frontierscience physics sequential retries",
        "dataset_revision": evaluate.DATASET_REVISION,
        "rounds": rounds,
        "policy": "After each judged round, exclude every successful problem from later rounds.",
        "config": asdict(config),
        "tracks": tracks,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--judge-model", default="gpt-5.6-sol")
    parser.add_argument("--judge-reasoning-effort", default="high")
    parser.add_argument(
        "--output-root", type=Path,
        default=BENCHMARK_ROOT / "artifacts" / "gpt-5.6-sol-high-best-of-5",
    )
    parser.add_argument(
        "--first-round", type=Path,
        default=BENCHMARK_ROOT / "artifacts" / "gpt-5.6-sol-high",
    )
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds must be at least 1")
    config = evaluate.Config(
        args.model, args.reasoning_effort, args.judge_model,
        args.judge_reasoning_effort, args.timeout,
    )
    benchmark_root = BENCHMARK_ROOT
    evaluate.download_data(benchmark_root / "data")
    args.output_root.mkdir(parents=True, exist_ok=True)
    round_one = args.output_root / "round-1"
    round_one.mkdir(exist_ok=True)
    for filename in ("generations.jsonl", "judgments.jsonl"):
        source = args.first_round / filename
        target = round_one / filename
        if not target.exists():
            target.write_bytes(source.read_bytes())

    all_rows = [
        (track, row)
        for track in evaluate.TRACKS
        for row in evaluate.load_physics(benchmark_root / "data", track)
    ]
    successful = successful_ids(read_jsonl(round_one / "judgments.jsonl"))
    for round_number in range(2, args.rounds + 1):
        round_dir = args.output_root / f"round-{round_number}"
        round_dir.mkdir(exist_ok=True)
        pending = [(track, row) for track, row in all_rows if row["_eval_id"] not in successful]
        manifest = {
            "round": round_number,
            "input_count": len(pending),
            "excluded_prior_successes": len(all_rows) - len(pending),
            "input_ids": [row["_eval_id"] for _, row in pending],
        }
        (round_dir / "selection.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"round {round_number}: evaluating {len(pending)} remaining problems", flush=True)
        if pending:
            generation_path = round_dir / "generations.jsonl"
            judgment_path = round_dir / "judgments.jsonl"
            generations = read_jsonl(generation_path)
            generation_by_id = {item["id"]: item for item in generations}
            judgment_ids = {item["id"] for item in read_jsonl(judgment_path)}
            from concurrent.futures import ThreadPoolExecutor, as_completed
            import threading

            lock = threading.Lock()
            missing = [(track, row) for track, row in pending if row["_eval_id"] not in generation_by_id]
            with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
                futures = {pool.submit(evaluate.generate_one, row, track, config): row["_eval_id"] for track, row in missing}
                for future in as_completed(futures):
                    item = future.result()
                    generation_by_id[item["id"]] = item
                    evaluate._write_jsonl(generation_path, item, lock)
                    print(f"round {round_number} generated {item['track']} {item['id']}", flush=True)
            row_by_id = {row["_eval_id"]: row for _, row in pending}
            missing_generations = [generation_by_id[row["_eval_id"]] for _, row in pending if row["_eval_id"] not in judgment_ids]
            with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
                futures = {
                    pool.submit(evaluate.judge_one, row_by_id[item["id"]], item, config): item["id"]
                    for item in missing_generations
                }
                for future in as_completed(futures):
                    item = future.result()
                    evaluate._write_jsonl(judgment_path, item, lock)
                    print(f"round {round_number} judged {item['track']} {item['id']}: {item['score']}", flush=True)
        round_judgments = read_jsonl(round_dir / "judgments.jsonl")
        successful.update(successful_ids(round_judgments))
        summary = cumulative_summary(args.output_root, round_number, config)
        (args.output_root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary["tracks"], indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
