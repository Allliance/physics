import json
from pathlib import Path
import unittest
import sys

# Make the runner modules importable from unittest discovery or direct execution.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hle_eval.claude import parse_events
from hle_eval.errors import GenerationLimitError


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

    def test_rejects_unavailable_requested_web_tools(self):
        init = {"type": "system", "subtype": "init", "tools": ["Bash", "Edit", "Read"]}
        events = json.dumps(init) + "\n" + self.events()
        with self.assertRaisesRegex(ValueError, "WebSearch"):
            parse_events(events, "gateway fable", expected_tools=["Bash", "WebSearch"])

    def test_records_available_web_tools_even_when_unused(self):
        tools = ["Bash", "WebSearch", "WebFetch"]
        init = {"type": "system", "subtype": "init", "tools": tools}
        result = parse_events(json.dumps(init) + "\n" + self.events(), "gateway fable", tools)
        self.assertEqual(result["available_tools"], tools)
        self.assertEqual(result["tool_events"], ["Bash"])

    def test_request_size_limit_is_distinct_from_transport_errors(self):
        for message, error_type in [("Request too large (max 32MB).", GenerationLimitError),
                                    ("Claude's response exceeded the 32768 output token maximum.", GenerationLimitError),
                                    ("The response stopped arriving.", ValueError)]:
            events = [json.loads(line) for line in self.events().splitlines()]
            events[-1].update(is_error=True, subtype="error_during_execution", result=message)
            with self.assertRaises(error_type) as caught:
                parse_events("\n".join(json.dumps(e) for e in events), "gateway fable")
            self.assertEqual(type(caught.exception), error_type)


if __name__ == "__main__":
    unittest.main()
