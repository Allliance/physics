#!/usr/bin/env python3
"""Run the frozen DeepSeek-V4-Pro max-reasoning physics evaluation suite."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from model_evals.kimi import run_suite as suite


suite.TAG = "deepseek-v4-pro-max-no-tools-20260917"
suite.RUN = suite.ROOT / "model_evals/deepseek/runs" / suite.TAG
suite.MODEL = "deepseek-v4-pro"
suite.MODEL_ID = "deepseek-ai/DeepSeek-V4-Pro"
suite.TEMPERATURE = 1.0
suite.TOP_P = 1.0


if __name__ == "__main__":
    raise SystemExit(suite.main())
