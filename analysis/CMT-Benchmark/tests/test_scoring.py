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

from cmt_eval import scoring as scoring
from cmt_eval import runner


def graded(**labels):
    return {qid: {"judge_response": {"correct": label}} for qid, label in labels.items()}


class AggregationTests(unittest.TestCase):
    def test_max_is_per_question_not_best_round_accuracy(self):
        rounds = [graded(a="yes", b="no"), graded(a="no", b="yes")]
        mean = scoring.aggregate_scores(["a", "b"], rounds, "mean")
        maximum = scoring.aggregate_scores(["a", "b"], rounds, "max")
        self.assertEqual(mean["final_score"], 0.5)
        self.assertEqual(maximum["final_score"], 1.0)
        self.assertEqual(maximum["round_scores"], [0.5, 0.5])
        self.assertEqual(maximum["per_question"]["a"]["round_scores"], [1, 0])

    def test_missing_scores_do_not_shrink_denominator(self):
        for mode in ["mean", "max"]:
            summary = scoring.aggregate_scores(["a", "b"], [graded(a="yes"), {}], mode)
            self.assertFalse(summary["complete"])
            self.assertIsNone(summary["final_score"])
            self.assertEqual(summary["missing_judgments"], 3)

    def test_single_round_aggregations_agree(self):
        for mode in ["mean", "max"]:
            self.assertEqual(scoring.aggregate_scores(["a"], [graded(a="no")], mode)["final_score"], 0)

    def test_invalid_grades_are_not_counted_as_incorrect(self):
        with self.assertRaises(ValueError):
            scoring.aggregate_scores(["a"], [graded(a="unknown")], "mean")


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
        with patch.object(scoring, "make_fable_client", return_value=client):
            judge = scoring.make_judge(args)
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
            judge = scoring.make_judge(runner.parse_args(["--model", "fable", "--use-tools"]))
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
                scoring.validate_judgment(content)


if __name__ == "__main__":
    unittest.main()
