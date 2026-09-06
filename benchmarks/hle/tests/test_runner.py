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

from hle_eval import backends, runner


QUESTIONS = [
    {"id": "image", "question": "Read the diagram", "category": "Physics",
     "image": "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nexample").decode()},
    {"id": "text", "question": "What is 2 + 2?", "category": "Physics", "image": ""},
    {"id": "text2", "question": "What is 3 + 3?", "category": "Physics", "image": ""},
]


class SelectionTests(unittest.TestCase):
    def test_images_are_opt_in_for_both_models(self):
        for model in ["GPT-5.6-Sol", "Fable"]:
            self.assertFalse(runner.parse_args(["--model", model]).include_images)
            self.assertTrue(runner.parse_args(["--model", model, "--include-images"]).include_images)
            self.assertFalse(runner.parse_args(["--model", model, "--no-include-images"]).include_images)

    def test_limit_is_applied_after_image_filter(self):
        selected = runner.select_questions(QUESTIONS, include_images=False, max_samples=1)
        self.assertEqual([q["id"] for q in selected], ["text"])
        self.assertEqual(len(runner.select_questions(QUESTIONS, include_images=True)), 3)

    def test_explicit_image_id_requires_opt_in(self):
        with self.assertRaisesRegex(ValueError, "--include-images"):
            runner.select_questions(QUESTIONS, include_images=False, requested_ids=["image"])
        self.assertEqual(len(runner.select_questions(QUESTIONS, include_images=True,
                                                    requested_ids=["image"])), 1)

    def test_unknown_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            runner.select_questions(QUESTIONS, include_images=True, requested_ids=["missing"])

    def test_invalid_cli_combinations_fail_before_model_calls(self):
        for args in [["--model", "opus"], ["--rounds", "0"],
                     ["--web-search", "live"], ["--max-samples", "0"], ["--num-workers", "0"],
                     ["--model", "gpt-5.6-sol", "--max-output-tokens", "100"]]:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
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

    def test_api_request_includes_image_effort_and_no_answers_or_tools(self):
        client = MagicMock()
        client.messages.stream.return_value.__enter__.return_value.get_final_message.return_value.model_dump.return_value = self.response()
        constructor = MagicMock(return_value=client)
        with patch.dict("sys.modules", {"anthropic": SimpleNamespace(Anthropic=constructor)}), \
                patch.dict(os.environ, {"ANTHROPIC_AUTH_TOKEN": "test-token"}, clear=True), \
                tempfile.TemporaryDirectory() as tmp:
            predict = runner.make_predictor(runner.parse_args(["--model", "fable"]), "gateway fable")
            image = runner.materialize_image(QUESTIONS[0]["image"], Path(tmp), "image")
            question = {**QUESTIONS[0], "answer": "DO NOT SEND REFERENCE ANSWER"}
            predict(question, image)
        request = client.messages.stream.call_args.kwargs
        self.assertEqual(request["model"], "gateway fable")
        self.assertEqual(request["output_config"], {"effort": "high"})
        self.assertEqual(request["thinking"], {"type": "adaptive"})
        self.assertNotIn("tools", request)
        self.assertNotIn("DO NOT SEND REFERENCE ANSWER", json.dumps(request))
        source = request["messages"][0]["content"][0]["source"]
        self.assertEqual(source["media_type"], "image/png")
        self.assertTrue(base64.b64decode(source["data"]).startswith(b"\x89PNG"))


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name) / "nested" / "predictions.json"
        self.args = ["--model", "fable", "--fable-model", "claude-fable-5", "--output", str(self.output)]

    def run_main(self, args, predictor):
        def judge(args, questions, answers, predictions, output, write_json):
            return {qid: {"judge_response": {"correct": "yes"}} for qid in predictions}

        with patch.object(runner, "load_questions", return_value=(QUESTIONS, ["Physics"])), \
                patch.object(runner, "load_answers", return_value={q["id"]: "4" for q in QUESTIONS}), \
                patch.object(runner, "judge_round", side_effect=judge), \
                patch.object(runner, "make_predictor", return_value=predictor) as factory, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = runner.main(args)
        return result, factory

    def test_resume_avoids_calls_and_preserves_judge_format(self):
        predict = MagicMock(return_value={"response": "Answer: 4", "usage": {}})
        self.assertEqual(self.run_main(self.args, predict)[0], 0)
        data = json.loads(self.output.read_text())
        self.assertEqual(set(data), {"text", "text2"})
        self.assertTrue(all(not row["has_image"] for row in data.values()))
        self.assertTrue(all(row["model"] == "claude-fable-5" and row["response"] for row in data.values()))
        _, factory = self.run_main(self.args, predict)
        factory.assert_not_called()
        self.assertEqual(predict.call_count, 2)

    def test_resume_rejects_changed_model_modality_effort_and_questions(self):
        self.run_main(self.args, lambda q, image: {"response": "Answer: 4"})
        for extra in [["--include-images"], ["--reasoning-effort", "low"],
                      ["--max-samples", "1"], ["--fable-model", "other"]]:
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "settings"):
                self.run_main(self.args + extra, MagicMock())
        with self.assertRaisesRegex(ValueError, "settings"):
            self.run_main(["--model", "gpt-5.6-sol", "--output", str(self.output)], MagicMock())

    def test_partial_failure_exits_nonzero_and_only_retries_missing(self):
        def predict(q, image):
            if q["id"] == "text2":
                raise RuntimeError("temporary failure")
            return {"response": "Answer: 4"}
        self.assertEqual(self.run_main(self.args, predict)[0], 1)
        self.assertEqual(set(json.loads(self.output.read_text())), {"text"})
        retry = MagicMock(return_value={"response": "Answer: 6"})
        self.assertEqual(self.run_main(self.args, retry)[0], 0)
        self.assertEqual(retry.call_count, 1)
        self.assertEqual(retry.call_args.args[0]["id"], "text2")

    def test_failure_records_distinguish_limits_and_clear_on_success(self):
        from hle_eval.errors import GenerationLimitError

        def predict(q, image):
            if q["id"] == "text":
                raise GenerationLimitError("token budget exhausted")
            raise RuntimeError("transport failed")

        self.assertEqual(self.run_main(self.args, predict)[0], 1)
        path = self.output.with_name("predictions.failures.json")
        failures = json.loads(path.read_text())
        self.assertTrue(failures["text"]["limit_exhausted"])
        self.assertFalse(failures["text2"]["limit_exhausted"])
        self.assertEqual(self.run_main(self.args, lambda q, image: {"response": "Answer: 4"})[0], 0)
        self.assertEqual(json.loads(path.read_text()), {})

    def test_fixed_limit_policy_reuses_failure_without_regenerating(self):
        from hle_eval.errors import GenerationLimitError

        exhausted = MagicMock(side_effect=GenerationLimitError("token budget exhausted"))
        self.assertEqual(self.run_main(self.args, exhausted)[0], 1)
        unused = MagicMock(side_effect=AssertionError("Retried a fixed-budget failure"))
        self.assertEqual(self.run_main(self.args + ["--limit-policy", "incorrect"], unused)[0], 0)
        unused.assert_not_called()
        data = json.loads(self.output.read_text())
        self.assertTrue(all(row["limit_exhausted"] and row["response_is_placeholder"] for row in data.values()))
        with self.assertRaisesRegex(ValueError, "Scored limit outcomes"):
            self.run_main(self.args, unused)

    def test_legacy_output_without_manifest_is_not_silently_reused(self):
        runner.write_json(self.output, {"text": {"model": "other", "response": "Answer: 4"}})
        with self.assertRaisesRegex(ValueError, "no run manifest"):
            self.run_main(self.args, MagicMock())

    def test_overlapping_rounds_keep_independent_checkpoints_and_resume(self):
        import threading

        barrier = threading.Barrier(2)

        def predict(question, image):
            barrier.wait(timeout=5)
            return {"response": "Answer: 4"}

        args = self.args + ["--rounds", "2", "--round-workers", "2",
                            "--num-workers", "2", "--max-samples", "1"]
        self.assertEqual(self.run_main(args, predict)[0], 0)
        for index in [1, 2]:
            path = runner.round_path(self.output, index)
            self.assertEqual(set(json.loads(path.read_text())), {"text"})
            self.assertEqual(json.loads(path.with_suffix(".json.meta.json").read_text())["round"], index)
        summary = json.loads(self.output.with_suffix(".summary.json").read_text())
        self.assertTrue(summary["complete"])
        self.assertEqual(summary["per_question"]["text"]["round_scores"], [1, 1])
        unused = MagicMock(side_effect=AssertionError("Regenerated a saved attempt"))
        self.assertEqual(self.run_main(args + ["--round-workers", "1"], unused)[0], 0)
        unused.assert_not_called()


if __name__ == "__main__":
    unittest.main()
