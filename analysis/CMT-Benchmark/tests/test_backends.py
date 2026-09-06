"""Network-free selection, request, and checkpoint regression tests."""

import base64
import contextlib
import io
import json
import os
import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Make the runner modules importable from unittest discovery or direct execution.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cmt_eval import backends, runner


class BackendRequestTests(unittest.TestCase):
    def test_sol_tools_and_prompt(self):
        event = {"item": {"type": "command_execution", "aggregated_output": "4"}}
        client = MagicMock()
        client.complete.return_value = SimpleNamespace(text="4", usage={}, attempts=1, events=[event])
        constructor = MagicMock(return_value=client)
        with patch.dict("sys.modules", {"codex_cli": SimpleNamespace(CodexLLM=constructor)}):
            args = runner.parse_args(["--use-tools"])
            result = backends.make_predictor(args, None)({"question": "Compute 2+2", "solution": "SECRET"}, None)
        self.assertEqual(client.complete.call_args.args, ("Compute 2+2",))
        self.assertFalse(constructor.call_args.kwargs["strict_no_tools"])
        self.assertEqual(constructor.call_args.kwargs["env_set"]["PATH"], runner.TOOL_PATH)
        self.assertIn("\\boxed{}", constructor.call_args.kwargs["system_prompt"])
        self.assertEqual(result["tool_trace"][0]["item"]["aggregated_output"], "4")

    def test_fable_request_contains_only_question_and_has_no_tools(self):
        client = MagicMock()
        client.messages.stream.return_value.__enter__.return_value.get_final_message.return_value.model_dump.return_value = {
            "model": "claude-fable-5", "content": [{"type": "text", "text": "4"}], "stop_reason": "end_turn"}
        with patch.object(backends, "make_fable_client", return_value=client):
            predict = backends.make_predictor(runner.parse_args(["--model", "fable"]), "gateway fable")
            predict({"question": "Compute 2+2", "solution": "SECRET"}, None)
        request = client.messages.stream.call_args.kwargs
        self.assertEqual(request["model"], "gateway fable")
        self.assertEqual(request["messages"], [{"role": "user", "content": [{"type": "text", "text": "Compute 2+2"}]}])
        self.assertEqual(request["output_config"], {"effort": "high"})
        self.assertEqual(request["thinking"], {"type": "adaptive"})
        self.assertNotIn("tools", request)

    def test_cli_policy_and_cross_model_judges(self):
        for model, judge in [("gpt-5.6-sol", "claude-fable-5"), ("fable", "gpt-5.6-sol")]:
            args = runner.parse_args(["--model", model])
            self.assertFalse(args.use_tools)
            self.assertEqual(args.judge_model, judge)
            self.assertEqual(args.web_search, "disabled")
            self.assertTrue((args.codex_cli_path / "codex_cli" / "__init__.py").is_file())
        for args in [["--judge-model", "gpt-5.6-sol"], ["--model", "other"],
                     ["--rounds", "0"], ["--num-workers", "0"], ["--max-samples", "0"],
                     ["--web-search", "live"], ["--max-output-tokens", "100"],
                     ["--model", "fable", "--use-tools", "--web-search", "cached"]]:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                runner.parse_args(args)


class FableTests(unittest.TestCase):
    def response(self, **updates):
        return {"model": "claude-fable-5", "content": [{"type": "text", "text": "Answer: 4"}],
                "stop_reason": "end_turn", "usage": {"output_tokens": 5}, **updates}

    def test_thinking_is_not_used_as_answer(self):
        data = self.response(content=[{"type": "thinking", "thinking": "private"},
                                      {"type": "text", "text": "Answer: 4"}])
        self.assertEqual(backends.parse_fable_response(data, "gateway fable")["response"], "Answer: 4")

    def test_refusal_is_recorded_without_fallback(self):
        data = backends.parse_fable_response(self.response(content=[], stop_reason="refusal"), "claude-fable-5")
        self.assertTrue(data["refused"])
        self.assertIn("Answer: None", data["response"])

    def test_wrong_model_truncation_empty_and_tools_are_rejected(self):
        for updates in [{"model": "claude-opus-5"}, {"model": "claude-fable-5-1"},
                        {"stop_reason": "max_tokens"}, {"content": []},
                        {"content": [{"type": "tool_use"}]}]:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                backends.parse_fable_response(self.response(**updates), "gateway fable")

    def test_mapping_precedence(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": tmp}, clear=True):
            self.assertEqual(backends.resolve_fable_model(None), "claude-fable-5")
            Path(tmp, "settings.json").write_text(json.dumps({"modelOverrides": {"claude-fable-5": "mapped"}}))
            self.assertEqual(backends.resolve_fable_model(None), "mapped")
            with patch.dict(os.environ, {"ANTHROPIC_DEFAULT_FABLE_MODEL": "env-model"}):
                self.assertEqual(backends.resolve_fable_model(None), "env-model")
                self.assertEqual(backends.resolve_fable_model("explicit"), "explicit")
