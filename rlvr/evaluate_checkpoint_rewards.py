"""Cross-score stored PRISM checkpoint generations with both RLVR rewards."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from rlvr import llm_judge_reward, reward


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        metavar="LABEL=VALIDATION_DIR",
        help="repeat for each run to evaluate",
    )
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--truth-dir",
        action="append",
        type=Path,
        default=[],
        help="validation directory used only to supply richer ground truths",
    )
    parser.add_argument("--native-workers", type=int, default=2)
    parser.add_argument("--llm-workers", type=int, default=4)
    return parser.parse_args()


def load_runs(specifications: list[str]) -> list[dict[str, Any]]:
    records = []
    for specification in specifications:
        label, separator, raw_directory = specification.partition("=")
        if not separator or not label or not raw_directory:
            raise ValueError(f"invalid --run value: {specification!r}")
        directory = Path(raw_directory)
        for path in sorted(directory.glob("*.jsonl"), key=lambda item: int(item.stem)):
            if not path.stem.isdigit():
                continue
            for line in path.read_text().splitlines():
                row = json.loads(line)
                truth = json.loads(row["gts"])
                records.append(
                    {
                        "run": label,
                        "step": int(path.stem),
                        "problem_id": truth["problem_id"],
                        "solution": row["output"],
                        "truth": truth,
                        "row": row,
                    }
                )
    return records


def record_key(record: dict[str, Any], grader: str) -> str:
    digest = hashlib.sha256(record["solution"].encode()).hexdigest()[:20]
    if grader == "llm":
        grader = f"llm-binary-{llm_judge_reward.BINARY_PROMPT.fingerprint}"
    return f"{record['run']}:{record['step']}:{record['problem_id']}:{digest}:{grader}"


def load_cache(path: Path) -> dict[str, dict[str, float]]:
    cache = {}
    if path.exists():
        for line in path.read_text().splitlines():
            item = json.loads(line)
            cache[item["key"]] = item["result"]
    return cache


def native_from_row(row: dict[str, Any]) -> dict[str, float] | None:
    if "process_score" not in row:
        return None
    return {
        "score": float(row["score"]),
        "acc": float(row["acc"]),
        "reward_error": float(row.get("reward_error") or 0.0),
        "reward_timeout": float(row.get("reward_timeout") or 0.0),
        "reward_resource_limit": float(row.get("reward_resource_limit") or 0.0),
    }


def llm_from_row(row: dict[str, Any]) -> dict[str, float] | None:
    if "binary_judge_score" not in row:
        return None
    return {
        "score": float(row["binary_judge_score"]),
        "acc": float(row["binary_judge_score"]),
        "judge_error": float(row.get("judge_error") or 0.0),
    }


def score_missing(
    records: list[dict[str, Any]],
    grader: str,
    workers: int,
    cache: dict[str, dict[str, float]],
    cache_path: Path,
) -> None:
    if grader == "native":
        available = native_from_row

        def score(record: dict[str, Any]) -> dict[str, float]:
            return reward.compute_score(
                reward.PRISM_SOURCE,
                record["solution"],
                record["truth"],
                timeout_seconds=20,
            )

    else:
        available = llm_from_row

        def score(record: dict[str, Any]) -> dict[str, float]:
            return llm_judge_reward.compute_score(
                llm_judge_reward.PRISM_SOURCE,
                record["solution"],
                record["truth"],
                extra_info={"split": "validation"},
                timeout_seconds=180,
            )

    missing = []
    for record in records:
        if available(record["row"]) is not None:
            continue
        cached = cache.get(record_key(record, grader))
        if cached is None or (grader == "llm" and cached.get("judge_error", 0.0)):
            missing.append(record)
    if not missing:
        print(f"{grader}: no missing scores", flush=True)
        return

    print(f"{grader}: scoring {len(missing)} responses with {workers} workers", flush=True)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    completed = 0
    with cache_path.open("a") as handle, ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(score, record): record for record in missing}
        for future in as_completed(futures):
            record = futures[future]
            result = future.result()
            key = record_key(record, grader)
            cache[key] = result
            handle.write(json.dumps({"key": key, "result": result}, separators=(",", ":")) + "\n")
            handle.flush()
            completed += 1
            if completed % 25 == 0 or completed == len(missing):
                print(f"{grader}: {completed}/{len(missing)}", flush=True)


def complete_truth(records: list[dict[str, Any]], truth_directories: list[Path]) -> None:
    by_problem = {
        record["problem_id"]: record["truth"]
        for record in records
        if record["truth"].get("problem") and record["truth"].get("reference_answer")
    }
    for directory in truth_directories:
        for path in directory.glob("*.jsonl"):
            for line in path.read_text().splitlines():
                truth = json.loads(json.loads(line)["gts"])
                if truth.get("problem") and truth.get("reference_answer"):
                    by_problem[truth["problem_id"]] = truth
    for record in records:
        full = by_problem.get(record["problem_id"])
        if full:
            record["truth"] = full
        elif not record["truth"].get("problem"):
            raise ValueError(f"no LLM-judge truth for {record['problem_id']}")


def result_for(
    record: dict[str, Any], grader: str, cache: dict[str, dict[str, float]]
) -> dict[str, float]:
    source = native_from_row(record["row"]) if grader == "native" else llm_from_row(record["row"])
    return source if source is not None else cache[record_key(record, grader)]


def write_summary(
    records: list[dict[str, Any]], cache: dict[str, dict[str, float]], output: Path
) -> None:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault((record["run"], record["step"]), []).append(record)

    rows = []
    for (run, step), group in sorted(grouped.items()):
        native = [result_for(record, "native", cache) for record in group]
        llm = [result_for(record, "llm", cache) for record in group]
        rows.append(
            {
                "run": run,
                "step": step,
                "samples": len(group),
                "sympy_reward": sum(item["score"] for item in native) / len(native),
                "sympy_accuracy": sum(item["acc"] for item in native) / len(native),
                "sympy_failure_rate": sum(
                    item.get("reward_error", 0.0)
                    + item.get("reward_timeout", 0.0)
                    + item.get("reward_resource_limit", 0.0)
                    for item in native
                )
                / len(native),
                "llm_judge_reward": sum(item["score"] for item in llm) / len(llm),
                "llm_judge_accuracy": sum(item["acc"] for item in llm) / len(llm),
                "llm_judge_failure_rate": sum(item.get("judge_error", 0.0) for item in llm)
                / len(llm),
            }
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    markdown = output.with_suffix(".md")
    with markdown.open("w") as handle:
        handle.write(
            "| Run | Step | N | SymPy reward | SymPy acc. | SymPy fail | "
            "Binary LLM reward | Binary LLM acc. | LLM fail |\n"
        )
        handle.write("|---|---:|---:|---:|---:|---:|---:|---:|---:|\n")
        for row in rows:
            handle.write(
                f"| {row['run']} | {row['step']} | {row['samples']} | "
                f"{row['sympy_reward']:.4f} | {row['sympy_accuracy']:.4f} | "
                f"{row['sympy_failure_rate']:.4f} | {row['llm_judge_reward']:.4f} | "
                f"{row['llm_judge_accuracy']:.4f} | {row['llm_judge_failure_rate']:.4f} |\n"
            )
    print(f"summary={output}", flush=True)
    print(f"report={markdown}", flush=True)


def main() -> None:
    args = parse_args()
    records = load_runs(args.run)
    complete_truth(records, args.truth_dir)
    cache = load_cache(args.cache)
    score_missing(records, "native", args.native_workers, cache, args.cache)
    score_missing(records, "llm", args.llm_workers, cache, args.cache)
    write_summary(records, cache, args.output)


if __name__ == "__main__":
    main()
