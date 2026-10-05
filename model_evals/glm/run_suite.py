#!/usr/bin/env python3
"""Run the frozen GLM-5.3 max-reasoning physics evaluation suite."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from model_evals.kimi import run_suite as suite


suite.TAG = "glm-5.3-max-no-tools-20260917"
suite.RUN = suite.ROOT / "model_evals/glm/runs" / suite.TAG
suite.MODEL = "glm-5.3"
suite.MODEL_ID = "zai-org/GLM-5.3"
suite.TEMPERATURE = 1.0
suite.TOP_P = 0.95


if __name__ == "__main__":
    raise SystemExit(suite.main())
