import json
from pathlib import Path
import unittest
import sys

# Make the runner modules importable from unittest discovery or direct execution.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hle_eval.claude import parse_events


class ClaudeToolTests(unittest.TestCase):
    def events(self, model="claude-fable-5", subtype="success", stop="end_turn"):
        return "\n".join(json.dumps(e) for e in [
            {"type": "assistant", "message": {"model": model, "stop_reason": "tool_use",
             "content": [{"type": "tool_use", "name": "Bash", "id": "call1", "input": {"command": "python3 -c 'print(4)'"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "call1", "content": "4"}]}},
            {"type": "assistant", "message": {"model": model, "stop_reason": stop,
             "content": [{"type": "text", "text": "Answer: 4"}]}},
            {"type": "result", "is_error": False, "subtype": subtype, "result": "Answer: 4", "num_turns": 2},
        ])

    def test_records_executed_tool_and_result(self):
        result = parse_events(self.events(), "gateway fable")
        self.assertEqual(result["tool_events"], ["Bash"])
        self.assertEqual(result["tool_results"][0]["content"], "4")
        self.assertEqual(result["response"], "Answer: 4")

    def test_rejects_fallback_and_turn_limit(self):
        for kwargs in [{"model": "claude-opus-5"}, {"subtype": "error_max_turns"}, {"stop": "max_tokens"}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                parse_events(self.events(**kwargs), "gateway fable")


if __name__ == "__main__":
    unittest.main()
