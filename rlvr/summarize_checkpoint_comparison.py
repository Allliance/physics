"""Summarize and plot matched checkpoint scores from the two PRISM RL runs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STEPS = (20, 40, 60, 80, 100)
RUNS = (
    (
        "sympy",
        "SymPy-trained",
        "qwen3-4b-prism-grpo-train-20260902T193745Z-20379",
    ),
    (
        "llm_judge",
        "LLM-judge-trained",
        "llm-judge-train-20403",
    ),
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _wilson_half_width(mean: float, n: int) -> float:
    if n == 0:
        return 0.0
    z = 1.959963984540054
    denominator = 1 + z * z / n
    radius = z * math.sqrt(mean * (1 - mean) / n + z * z / (4 * n * n)) / denominator
    return radius


def summarize(root: Path, expected_rows: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run_key, run_label, source_run in RUNS:
        for step in STEPS:
            generation_path = root / "generations" / f"{run_key}_trained" / f"step_{step}" / "validation" / f"{step}.jsonl"
            judgment_path = root / "judgments" / f"{run_key}_trained" / f"step_{step}.jsonl"
            generations = _read_jsonl(generation_path)
            if len(generations) != expected_rows:
                raise ValueError(f"{generation_path} has {len(generations)} rows, expected {expected_rows}")
            latest_judgments: dict[str, dict[str, Any]] = {}
            for judgment in _read_jsonl(judgment_path):
                latest_judgments[str(judgment["uid"])] = judgment
            completed = [row for row in latest_judgments.values() if row.get("status") == "completed"]
            errors = [row for row in latest_judgments.values() if row.get("status") != "completed"]
            if len(latest_judgments) != expected_rows:
                raise ValueError(
                    f"{judgment_path} has {len(latest_judgments)} judged rows, expected {expected_rows}"
                )

            sympy_values = [float(row["acc"]) for row in generations]
            native_rewards = [float(row["score"]) for row in generations]
            # Match the online binary reward wrapper: any judge/parsing failure
            # fails closed to zero rather than being removed from the denominator.
            judge_values = [
                float(row["grade"]) if row.get("status") == "completed" else 0.0
                for row in latest_judgments.values()
            ]
            sympy_mean = _mean(sympy_values)
            judge_mean = _mean(judge_values)
            assert sympy_mean is not None and judge_mean is not None
            rows.append(
                {
                    "training_reward": run_key,
                    "training_reward_label": run_label,
                    "source_run": source_run,
                    "step": step,
                    "rollouts": len(generations),
                    "sympy_accuracy": sympy_mean,
                    "sympy_wilson_half_width_95": _wilson_half_width(sympy_mean, len(sympy_values)),
                    "native_shaped_reward": _mean(native_rewards),
                    "llm_judge_accuracy": judge_mean,
                    "llm_judge_wilson_half_width_95": _wilson_half_width(judge_mean, len(judge_values)),
                    "judge_completed": len(completed),
                    "judge_errors": len(errors),
                    "generation_file": str(generation_path),
                    "judgment_file": str(judgment_path),
                }
            )
    return rows


def write_outputs(root: Path, rows: list[dict[str, Any]], dataset: Path) -> None:
    csv_path = root / "checkpoint_scores.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# Qwen3-4B checkpoint comparison",
        "",
        "| Training reward | Step | Rollouts | SymPy accuracy | Binary LLM-judge accuracy | Judge errors | Native shaped reward |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['training_reward_label']} | {row['step']} | {row['rollouts']} | "
            f"{row['sympy_accuracy']:.3f} | {row['llm_judge_accuracy']:.3f} | {row['judge_errors']} | "
            f"{row['native_shaped_reward']:.3f} |"
        )
    (root / "checkpoint_scores.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset),
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "validation_rows": 200,
        "steps": list(STEPS),
        "training_runs": {key: source for key, _label, source in RUNS},
        "generated_rollouts": sum(int(row["rollouts"]) for row in rows),
        "generation": {
            "model": "Qwen/Qwen3-4B",
            "validation_sampling": "greedy",
            "max_response_tokens": 2048,
            "rollouts_per_prompt": 1,
        },
        "scorers": {
            "sympy": "UGPhysics released auto-judge (strict extraction, precision=1e-2)",
            "llm_judge": (
                "Qwen/Qwen3.5-27B binary correctness judge, thinking budget 4096; "
                "judge/parsing errors fail closed to reward 0"
            ),
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    import matplotlib.pyplot as plt

    colors = {"sympy": "#2563eb", "llm_judge": "#dc2626"}
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.3), layout="constrained")
    metrics = (
        ("sympy_accuracy", "sympy_wilson_half_width_95", "SymPy scorer accuracy"),
        ("llm_judge_accuracy", "llm_judge_wilson_half_width_95", "Binary LLM-judge accuracy"),
    )
    for axis, (metric, error_metric, title) in zip(axes, metrics, strict=True):
        for run_key, run_label, _source in RUNS:
            run_rows = [row for row in rows if row["training_reward"] == run_key]
            x = [int(row["step"]) for row in run_rows]
            y = [float(row[metric]) for row in run_rows]
            yerr = [float(row[error_metric]) for row in run_rows]
            axis.errorbar(
                x,
                y,
                yerr=yerr,
                marker="o",
                linewidth=2,
                capsize=3,
                color=colors[run_key],
                label=run_label,
            )
            label_offset = 9 if run_key == "sympy" else -16
            for step, value in zip(x, y, strict=True):
                axis.annotate(
                    f"{value:.3f}",
                    (step, value),
                    xytext=(0, label_offset),
                    textcoords="offset points",
                    ha="center",
                    fontsize=8,
                )
        axis.set_title(title)
        axis.set_xlabel("Training step")
        axis.set_xticks(STEPS)
        axis.set_ylabel("Accuracy on UGPhysics validation (n=200)")
        axis.grid(alpha=0.25)
    axes[0].set_ylim(-0.005, 0.12)
    axes[1].set_ylim(0.10, 0.42)
    axes[1].legend(loc="best")
    fig.suptitle("Qwen3-4B PRISM RL: checkpoint performance by training reward", fontsize=16)
    fig.savefig(root / "checkpoint_scores.png", dpi=180, bbox_inches="tight")
    fig.savefig(root / "checkpoint_scores.pdf", bbox_inches="tight")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent / "runs" / "comparison-ugphysics-200",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).resolve().parent / "data" / "ugphysics" / "validation.parquet",
    )
    parser.add_argument("--expected-rows", type=int, default=200)
    args = parser.parse_args()
    rows = summarize(args.root, args.expected_rows)
    write_outputs(args.root, rows, args.dataset)
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
