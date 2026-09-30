"""Prompt text and output schemas shared by evaluation backends and judging."""

import json
from pathlib import Path

_ROOT = Path(__file__).parent
SYSTEM_PROMPT = (_ROOT / "prediction_no_tools.txt").read_text().strip()
TOOLS_SYSTEM_PROMPT = (_ROOT / "prediction_tools.txt").read_text().strip()
JUDGE_PROMPT = (_ROOT / "judge.txt").read_text()
JUDGE_SYSTEM_PROMPT = (_ROOT / "judge_system.txt").read_text()
JUDGE_SCHEMA = json.loads((_ROOT / "judge_schema.json").read_text())
