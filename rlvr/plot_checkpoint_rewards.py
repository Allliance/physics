"""Plot native and binary LLM-judge checkpoint evaluation rewards."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with args.csv_path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"no checkpoint results in {args.csv_path}")

    steps = [int(row["step"]) for row in rows]
    sympy = [float(row["sympy_reward"]) for row in rows]
    binary = [float(row["llm_judge_reward"]) for row in rows]

    figure, axis = plt.subplots(figsize=(10, 5.5))
    axis.plot(steps, sympy, marker="o", linewidth=2, label="SymPy reward")
    axis.plot(steps, binary, marker="o", linewidth=2, label="Binary LLM judge")
    axis.set(
        title="Qwen3-4B PRISM checkpoint evaluation",
        xlabel="SymPy RL training step",
        ylabel="Mean reward",
        ylim=(0.0, 1.0),
    )
    axis.grid(alpha=0.25)
    axis.legend()
    figure.tight_layout()
    output = args.output or args.csv_path.with_suffix(".png")
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    print(output)


if __name__ == "__main__":
    main()
