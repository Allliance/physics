import contextlib
import io
import json
import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Make the runner modules importable from unittest discovery or direct execution.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hle_eval import scoring as hle_scoring
from hle_eval import runner
from test_runner import QUESTIONS


def graded(**labels):
    return {qid: {"judge_response": {"correct": label}} for qid, label in labels.items()}


class AggregationTests(unittest.TestCase):
    def test_max_is_per_question_not_best_round_accuracy(self):
        rounds = [graded(a="yes", b="no"), graded(a="no", b="yes")]
        mean = hle_scoring.aggregate_scores(["a", "b"], rounds, "mean")
        maximum = hle_scoring.aggregate_scores(["a", "b"], rounds, "max")
        self.assertEqual(mean["final_score"], 0.5)
        self.assertEqual(maximum["final_score"], 1.0)
        self.assertEqual(maximum["round_scores"], [0.5, 0.5])
        self.assertEqual(maximum["per_question"]["a"]["round_scores"], [1, 0])

    def test_missing_scores_do_not_shrink_denominator(self):
        for mode in ["mean", "max"]:
            summary = hle_scoring.aggregate_scores(["a", "b"], [graded(a="yes"), {}], mode)
            self.assertFalse(summary["complete"])
            self.assertIsNone(summary["final_score"])
            self.assertEqual(summary["missing_judgments"], 3)

    def test_single_round_aggregations_agree(self):
        for mode in ["mean", "max"]:
            self.assertEqual(hle_scoring.aggregate_scores(["a"], [graded(a="no")], mode)["final_score"], 0)

    def test_invalid_grades_are_not_counted_as_incorrect(self):
        with self.assertRaises(ValueError):
            hle_scoring.aggregate_scores(["a"], [graded(a="unknown")], "mean")


class RoundPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name) / "run.json"
        self.args = ["--output", str(self.output), "--num-workers", "1"]
        self.counts = {}

    def predictor(self, q, image):
        qid = q["id"]
        self.counts[qid] = self.counts.get(qid, 0) + 1
        correct = (qid == "text" and self.counts[qid] == 1) or (qid == "text2" and self.counts[qid] == 2)
        return {"response": "yes" if correct else "no"}

    def run_main(self, args, judge=None):
        if judge is None:
            judge = lambda q, p, a: {"correct": p["response"]}
        with patch.object(runner, "load_questions", return_value=(QUESTIONS, ["Physics"])), \
                patch.object(runner, "load_answers", return_value={q["id"]: "answer" for q in QUESTIONS}), \
                patch.object(runner, "make_predictor", return_value=self.predictor) as predictions, \
                patch.object(hle_scoring, "make_judge", return_value=judge) as judgments, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = runner.main(args)
        return result, predictions, judgments

    def summary(self):
        return json.loads(self.output.with_suffix(".summary.json").read_text())

    def test_extend_rounds_and_reaggregate_without_repeating_calls(self):
        self.assertEqual(self.run_main(self.args)[0], 0)
        first_round = self.output.read_bytes()
        self.assertEqual(self.run_main(self.args + ["--rounds", "2"])[0], 0)
        self.assertEqual(self.output.read_bytes(), first_round)
        self.assertEqual(self.counts, {"text": 2, "text2": 2})
        self.assertEqual(self.summary()["final_score"], 0.5)
        result, predictions, judgments = self.run_main(self.args + ["--rounds", "2", "--aggregation", "max"])
        self.assertEqual(result, 0)
        predictions.assert_not_called()
        judgments.assert_not_called()
        self.assertEqual(self.summary()["final_score"], 1)

    def test_exclusions_apply_before_limit_in_every_round(self):
        path = Path(self.tmp.name) / "exclude.json"
        path.write_text(json.dumps(["text", "unrelated-id"]))
        args = self.args + ["--rounds", "2", "--max-samples", "1", "--exclude-ids-file", str(path)]
        self.assertEqual(self.run_main(args)[0], 0)
        self.assertEqual(self.counts, {"text2": 2})
        self.assertEqual(self.summary()["questions"], 1)
        for index in [1, 2]:
            self.assertEqual(set(json.loads(runner.round_path(self.output, index).read_text())), {"text2"})

    def test_failed_judge_retries_without_regenerating(self):
        def fail(q, p, a):
            if q["id"] == "text2":
                raise RuntimeError("transient judge error")
            return {"correct": p["response"]}
        self.assertEqual(self.run_main(self.args, fail)[0], 1)
        self.assertIsNone(self.summary()["final_score"])
        retry = MagicMock(return_value={"correct": "no"})
        result, predictions, _ = self.run_main(self.args, retry)
        self.assertEqual(result, 0)
        predictions.assert_not_called()
        retry.assert_called_once()
        self.assertEqual(retry.call_args.args[0]["id"], "text2")

    def test_judge_cache_rejects_changed_predictions(self):
        self.run_main(self.args)
        predictions = json.loads(self.output.read_text())
        predictions["text"]["response"] = "changed answer"
        self.output.write_text(json.dumps(predictions))
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.run_main(self.args)

    def test_exclusion_file_must_be_a_list_of_strings(self):
        path = Path(self.tmp.name) / "exclude.json"
        for value in [{"ids": ["text"]}, [123], "text"]:
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "JSON list"):
                runner.read_ids(path, "--exclude-ids-file")
        self.assertIsNone(runner.read_ids(None, "--exclude-ids-file"))
        path.write_text("[]")
        self.assertEqual(runner.read_ids(path, "--exclude-ids-file"), [])


class ArgumentTests(unittest.TestCase):
    def test_cross_model_judging_is_automatic_and_enforced(self):
        for evaluated, judge in [("gpt-5.6-sol", "claude-fable-5"), ("fable", "gpt-5.6-sol")]:
            self.assertEqual(runner.parse_args(["--model", evaluated]).judge_model, judge)
            self.assertEqual(runner.parse_args(["--model", evaluated, "--judge-model", judge]).judge_model, judge)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                runner.parse_args(["--model", evaluated, "--judge-model", evaluated])

    def test_sol_tools_have_a_usable_path_and_keep_command_results(self):
        event = {"type": "item.completed", "item": {"type": "command_execution",
                 "command": "python3 -c 'print(4)'", "aggregated_output": "4", "exit_code": 0}}
        client = MagicMock()
        client.complete.return_value = SimpleNamespace(text="4", usage={}, attempts=1, events=[event])
        constructor = MagicMock(return_value=client)
        with patch.dict("sys.modules", {"codex_cli": SimpleNamespace(CodexLLM=constructor)}):
            args = runner.parse_args(["--use-tools"])
            result = runner.make_predictor(args, None)({"question": "Calculate 2+2"}, None)
            self.assertEqual(constructor.call_args.kwargs["env_set"]["PATH"], runner.TOOL_PATH)
            self.assertFalse(constructor.call_args.kwargs["strict_no_tools"])
            self.assertEqual(result["tool_trace"][0]["item"]["aggregated_output"], "4")

    def test_defaults_and_tool_toggle(self):
        for model in ["fable", "gpt-5.6-sol"]:
            args = runner.parse_args(["--model", model])
            self.assertFalse(args.use_tools)
            self.assertEqual(args.rounds, 1)
            self.assertEqual(args.aggregation, "mean")
            self.assertIsNone(args.exclude_ids_file)
            self.assertEqual(args.web_search, "disabled")
            args = runner.parse_args(["--model", model, "--use-tools"])
            self.assertTrue(args.use_tools)
            self.assertEqual(args.web_search, "live")
            self.assertFalse(runner.parse_args(["--no-use-tools"]).use_tools)
            self.assertTrue(runner.parse_args(["--allow-tools"]).use_tools)

    def test_excluding_explicit_image_id_takes_precedence(self):
        selected = runner.select_questions(QUESTIONS, include_images=False,
                                            requested_ids=["image", "text"], excluded_ids=["image"])
        self.assertEqual([q["id"] for q in selected], ["text"])


class JudgeBackendTests(unittest.TestCase):
    def content(self):
        return {"extracted_final_answer": "4", "reasoning": "Matches.",
                "correct": "yes", "confidence": 100, "strict": True}

    def message(self, **updates):
        return {"model": "claude-fable-5", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": json.dumps(self.content())}], **updates}

    def fable_judge(self, message):
        client = MagicMock()
        client.messages.stream.return_value.__enter__.return_value.get_final_message.return_value.model_dump.return_value = message
        args = runner.parse_args(["--model", "gpt-5.6-sol", "--use-tools", "--fable-model", "gateway fable"])
        with patch.object(hle_scoring, "make_fable_client", return_value=client):
            judge = hle_scoring.make_judge(args)
        return judge, client

    def test_fable_judges_gpt_through_api_without_tools(self):
        judge, client = self.fable_judge(self.message())
        result = judge({"question": "2+2?"}, {"response": "4"}, "4")
        request = client.messages.stream.call_args.kwargs
        self.assertEqual(request["model"], "gateway fable")
        self.assertNotIn("tools", request)
        self.assertIn('"strict"', request["messages"][0]["content"])
        self.assertEqual(result["actual_model"], "claude-fable-5")
        self.assertEqual(result["correct"], "yes")

    def test_gpt_judges_fable_through_codex_without_tools(self):
        client = MagicMock()
        client.complete.return_value = SimpleNamespace(text=json.dumps(self.content()))
        constructor = MagicMock(return_value=client)
        with patch.dict("sys.modules", {"codex_cli": SimpleNamespace(CodexLLM=constructor)}):
            judge = hle_scoring.make_judge(runner.parse_args(["--model", "fable", "--use-tools"]))
            result = judge({"question": "2+2?"}, {"response": "4"}, "4")
        self.assertEqual(constructor.call_args.kwargs["model"], "gpt-5.6-sol")
        self.assertTrue(constructor.call_args.kwargs["strict_no_tools"])
        self.assertEqual(constructor.call_args.kwargs["web_search"], "disabled")
        self.assertEqual(result["correct"], "yes")

    def test_fable_judge_refusals_wrong_models_and_truncation_are_failures(self):
        for updates in [{"stop_reason": "refusal", "content": []},
                        {"model": "claude-opus-5"}, {"stop_reason": "max_tokens"}]:
            judge, _ = self.fable_judge(self.message(**updates))
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                judge({"question": "2+2?"}, {"response": "4"}, "4")

    def test_invalid_json_judgments_are_rejected(self):
        for content in [{}, {**self.content(), "strict": False},
                        {**self.content(), "confidence": True}, {**self.content(), "correct": "maybe"}]:
            with self.subTest(content=content), self.assertRaises(ValueError):
                hle_scoring.validate_judgment(content)

    def test_limit_exhaustion_scores_zero_without_model_call(self):
        judge, client = self.fable_judge(self.message())
        result = judge({"question": "2+2?"},
                       {"response": "[No completed answer]", "limit_exhausted": True}, "4")
        self.assertEqual(result["correct"], "no")
        client.messages.stream.assert_not_called()


if __name__ == "__main__":
    unittest.main()
