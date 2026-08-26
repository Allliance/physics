#!/usr/bin/env python3
"""Run a reproducible random UGPhysics sample through the local Codex CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen


BENCHMARK_ROOT = Path(__file__).resolve().parent
REPO_ROOT = BENCHMARK_ROOT.parents[1]
CODE_ROOT = BENCHMARK_ROOT / "codes"
sys.path.insert(0, str(REPO_ROOT))
from utils.codex_cli import CodexLLM  # noqa: E402

# The upstream UGPhysics code uses a top-level module named ``utils``. Import
# it under that expected name only after retaining the repository wrapper.
sys.path.insert(0, str(CODE_ROOT))
for module_name in ("utils.codex_cli", "utils"):
    sys.modules.pop(module_name, None)
from judge import Judger  # noqa: E402
from utils import make_prompt  # type: ignore[attr-defined]  # noqa: E402


DATASET_REVISION = "523e71bc4e33356bb19de4af38c128796e8a8770"
DATASET_URL = (
    "https://huggingface.co/datasets/UGPhysics/ugphysics/resolve/"
    f"{DATASET_REVISION}/{{subject}}/{{language}}.jsonl"
)
SUBJECTS = (
    "AtomicPhysics",
    "ClassicalElectromagnetism",
    "ClassicalMechanics",
    "Electrodynamics",
    "GeometricalOptics",
    "QuantumMechanics",
    "Relativity",
    "SemiconductorPhysics",
    "Solid-StatePhysics",
    "StatisticalMechanics",
    "TheoreticalMechanics",
    "Thermodynamics",
    "WaveOptics",
)
LANGUAGES = ("en",)
SYSTEM_PROMPT = (
    "Solve the supplied undergraduate physics problem yourself. Give a rigorous, "
    "self-contained solution and obey its requested answer format. Do not use tools, "
    "files, web search, or external context."
)


@dataclass(frozen=True)
class Config:
    model: str
    reasoning_effort: str
    sample_size: int
    seed: int
    timeout: float


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def append_jsonl(path: Path, item: dict[str, Any], lock: threading.Lock) -> None:
    with lock, path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        handle.flush()


def download_dataset(data_dir: Path) -> None:
    for subject in SUBJECTS:
        for language in LANGUAGES:
            target = data_dir / subject / f"{language}.jsonl"
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with urlopen(
                DATASET_URL.format(subject=subject, language=language), timeout=120
            ) as response:
                payload = response.read()
            target.write_bytes(payload)


def load_dataset(data_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for subject in SUBJECTS:
        for language in LANGUAGES:
            for index, row in enumerate(read_jsonl(data_dir / subject / f"{language}.jsonl")):
                row["_eval_id"] = f"{subject}/{language}/{index}"
                rows.append(row)
    return rows


def dataset_digest(rows: list[dict[str, Any]]) -> str:
    payload = "\n".join(row["_eval_id"] for row in rows).encode()
    return hashlib.sha256(payload).hexdigest()


def select_sample(
    rows: list[dict[str, Any]], sample_path: Path, size: int, seed: int
) -> list[dict[str, Any]]:
    if sample_path.exists():
        sample = read_jsonl(sample_path)
        if len(sample) != size:
            raise ValueError(
                f"Existing sample has {len(sample)} rows, but --sample-size is {size}. "
                "Use a different output directory."
            )
        return sample
    if size > len(rows):
        raise ValueError(f"Cannot sample {size} rows from a dataset of {len(rows)}")
    sample = random.Random(seed).sample(rows, size)
    sample_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in sample),
        encoding="utf-8",
    )
    return sample


def generate(row: dict[str, Any], config: Config) -> dict[str, Any]:
    prompt = f"{make_prompt(row)}\n\n{row['problem']}"
    result = CodexLLM(
        model=config.model,
        model_reasoning_effort=config.reasoning_effort,
        timeout=config.timeout,
    ).complete(prompt, system_prompt=SYSTEM_PROMPT)
    return {
        "id": row["_eval_id"],
        "subject": row["subject"],
        "language": row["language"],
        "completion": result.text,
        "usage": result.usage,
        "wrapper_attempts": result.attempts,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def score(row: dict[str, Any], generation: dict[str, Any], judger: Judger) -> dict[str, Any]:
    correct = bool(judger.auto_judge(generation["completion"], row["answers"], precision=1e-2))
    return {
        "id": row["_eval_id"],
        "subject": row["subject"],
        "language": row["language"],
        "correct": correct,
        "reference_answer": row["answers"],
        "extracted_answer": judger.extract_ans(generation["completion"]),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def summarize(
    rows: list[dict[str, Any]], scores: list[dict[str, Any]], config: Config, digest: str
) -> dict[str, Any]:
    grouped: dict[str, list[bool]] = defaultdict(list)
    for item in scores:
        grouped[f"language/{item['language']}"].append(item["correct"])
        grouped[f"subject/{item['subject']}"].append(item["correct"])
    correct = sum(item["correct"] for item in scores)
    return {
        "benchmark": "UGPhysics/ugphysics",
        "dataset_revision": DATASET_REVISION,
        "dataset_id_digest": digest,
        "config": asdict(config),
        "sampling": "Uniform without replacement over the 5,520 released English problems.",
        "scoring": "UGPhysics released deterministic auto_judge, precision=1e-2; no auxiliary LLM judge.",
        "dataset_rows": len(rows),
        "completed": len(scores),
        "correct": correct,
        "accuracy": correct / len(scores) if scores else None,
        "breakdown": {
            key: {
                "total": len(values),
                "correct": sum(values),
                "accuracy": sum(values) / len(values),
            }
            for key, values in sorted(grouped.items())
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260826)
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BENCHMARK_ROOT / "artifacts" / "gpt-5.6-sol-high-random-100",
    )
    args = parser.parse_args()
    if args.sample_size < 1:
        parser.error("--sample-size must be positive")
    if args.max_workers < 1:
        parser.error("--max-workers must be positive")

    config = Config(
        args.model, args.reasoning_effort, args.sample_size, args.seed, args.timeout
    )
    data_dir = BENCHMARK_ROOT / "data" / "dataset"
    download_dataset(data_dir)
    rows = load_dataset(data_dir)
    digest = dataset_digest(rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    sample = select_sample(
        rows, args.output_dir / "sample.jsonl", args.sample_size, args.seed
    )
    manifest = {
        "benchmark": "UGPhysics/ugphysics",
        "dataset_revision": DATASET_REVISION,
        "dataset_rows": len(rows),
        "dataset_id_digest": digest,
        "config": asdict(config),
        "sample_ids": [row["_eval_id"] for row in sample],
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    generation_path = args.output_dir / "generations.jsonl"
    score_path = args.output_dir / "scores.jsonl"
    generations = {item["id"]: item for item in read_jsonl(generation_path)}
    lock = threading.Lock()
    missing = [row for row in sample if row["_eval_id"] not in generations]
    print(f"dataset: {len(rows)} rows; sample: {len(sample)}; pending: {len(missing)}", flush=True)
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {pool.submit(generate, row, config): row["_eval_id"] for row in missing}
        for future in as_completed(futures):
            item = future.result()
            generations[item["id"]] = item
            append_jsonl(generation_path, item, lock)
            print(f"generated {item['id']} ({len(generations)}/{len(sample)})", flush=True)

    existing_scores = {item["id"]: item for item in read_jsonl(score_path)}
    judger = Judger(strict_extract=True)
    for row in sample:
        item_id = row["_eval_id"]
        if item_id in existing_scores:
            continue
        item = score(row, generations[item_id], judger)
        existing_scores[item_id] = item
        append_jsonl(score_path, item, lock)
        print(f"scored {item_id}: {item['correct']}", flush=True)

    ordered_scores = [existing_scores[row["_eval_id"]] for row in sample]
    summary = summarize(rows, ordered_scores, config, digest)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
