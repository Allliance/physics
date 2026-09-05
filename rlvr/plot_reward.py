"""Plot raw and trailing-mean PRISM rewards from verl console logs."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


STEP_REWARD = re.compile(
    r"training/global_step:(\d+).*?critic/(?:score|rewards)/mean:([0-9.eE+-]+)"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--validation-dir", type=Path)
    parser.add_argument("--window", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def training_rewards(logs: list[Path]) -> list[tuple[int, float]]:
    by_step: dict[int, float] = {}
    for log in logs:
        for match in STEP_REWARD.finditer(log.read_text(errors="replace")):
            by_step[int(match.group(1))] = float(match.group(2))
    return sorted(by_step.items())


def validation_rewards(directory: Path | None) -> list[tuple[int, float]]:
    if directory is None:
        return []
    results = []
    for path in directory.glob("*.jsonl"):
        if not path.stem.isdigit():
            continue
        scores = [float(json.loads(line)["score"]) for line in path.read_text().splitlines()]
        if scores:
            results.append((int(path.stem), sum(scores) / len(scores)))
    return sorted(results)


def main() -> None:
    args = parse_args()
    if args.window < 1:
        raise ValueError("--window must be positive")
    rewards = training_rewards(args.logs)
    if len(rewards) < args.window:
        raise ValueError(f"need at least {args.window} logged training steps")

    steps = [step for step, _ in rewards]
    raw = [reward for _, reward in rewards]
    rolling_steps = steps[args.window - 1 :]
    rolling = [
        sum(raw[index - args.window + 1 : index + 1]) / args.window
        for index in range(args.window - 1, len(raw))
    ]
    validation = validation_rewards(args.validation_dir)

    # Imported here so parsing and unit use do not require plotting packages.
    import matplotlib.pyplot as plt

    plt.style.use("seaborn-v0_8-whitegrid")
    figure, axis = plt.subplots(figsize=(11, 6), dpi=160)
    axis.plot(steps, raw, color="#8da0cb", alpha=0.35, linewidth=1, label="Training reward")
    axis.scatter(steps, raw, color="#8da0cb", alpha=0.45, s=11)
    axis.plot(
        rolling_steps,
        rolling,
        color="#d62728",
        linewidth=2.6,
        label=f"Trailing {args.window}-step mean",
    )
    if validation:
        val_steps, val_rewards = zip(*validation)
        axis.plot(
            val_steps,
            val_rewards,
            color="#2ca02c",
            marker="D",
            markersize=5,
            linewidth=1.5,
            label="Validation mean reward",
        )
    axis.axvline(60, color="#555555", linestyle="--", linewidth=1, alpha=0.7)
    axis.text(60.8, axis.get_ylim()[1] * 0.94, "resume", color="#555555", fontsize=9)
    axis.set(title="Qwen3-4B PRISM reward", xlabel="Training step", ylabel="Mean reward")
    axis.set_xlim(left=0)
    axis.set_ylim(bottom=0)
    axis.legend(loc="upper left", frameon=True)
    figure.tight_layout()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output)
    plt.close(figure)

    csv_path = args.output.with_suffix(".csv")
    rolling_by_step = dict(zip(rolling_steps, rolling))
    with csv_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("step", "training_reward", f"rolling_{args.window}"))
        for step, reward in rewards:
            writer.writerow((step, reward, rolling_by_step.get(step, "")))

    print(f"latest_step={steps[-1]}")
    print(f"latest_reward={raw[-1]:.6f}")
    print(f"latest_rolling_{args.window}={rolling[-1]:.6f}")
    print(f"plot={args.output}")
    print(f"data={csv_path}")


if __name__ == "__main__":
    main()
