"""Versioned prompts used in run fingerprints."""

import json
from pathlib import Path

DIRECTORY = Path(__file__).parent
PREDICTION = (DIRECTORY / "prediction_no_tools.txt").read_text().strip()
PREDICTION_TOOLS = (DIRECTORY / "prediction_tools.txt").read_text().strip()
JUDGE_SYSTEM = (DIRECTORY / "judge_system.txt").read_text().strip()
JUDGE = (DIRECTORY / "judge.txt").read_text().strip()
JUDGE_SCHEMA = json.loads((DIRECTORY / "judge_schema.json").read_text())
