import json
import unittest
from pathlib import Path

from extract_ground_truths import (
    Config,
    ExtractionValidationError,
    RowExtractionError,
    collect_null_answers,
    extract_one,
    failed_row_record,
    infer_part_labels,
    is_ordered_token_subsequence,
    parse_and_verify,
    sub_questions,
)


class InferPartLabelsTest(unittest.TestCase):
    def test_single_part_is_a(self):
        self.assertEqual(infer_part_labels("Find x.", False), ["a"])

    def test_consecutive_labels_ignore_later_incidental_marker(self):
        question = "(a) Find x. (b) Find y using coefficient (d)."
        self.assertEqual(infer_part_labels(question, True), ["a", "b"])

    def test_multi_part_requires_a_and_b(self):
        with self.assertRaises(ValueError):
            infer_part_labels("Find x and y.", True)


class OrderedTokenVerificationTest(unittest.TestCase):
    solution = "First $x = 2$. Irrelevant derivation. Finally $y = 3\\,\\mathrm{m}$."

    def test_accepts_noncontiguous_ordered_solution_tokens(self):
        response = json.dumps(
            {
                "ground_truths": {"a": "$x = 2$. $y = 3\\,\\mathrm{m}$."},
                "null_answer_reasons": {},
            }
        )
        self.assertEqual(
            parse_and_verify(response, self.solution, ["a"]),
            ({"a": "$x = 2$. $y = 3\\,\\mathrm{m}$."}, {}),
        )

    def test_rejects_novel_or_reordered_tokens(self):
        self.assertFalse(is_ordered_token_subsequence("$y = 3\\,\\mathrm{m}$. $x", self.solution))
        response = json.dumps(
            {"ground_truths": {"a": "$x = 99$."}, "null_answer_reasons": {}}
        )
        with self.assertRaisesRegex(ExtractionValidationError, "absent from"):
            parse_and_verify(response, self.solution, ["a"])

    def test_ignores_math_delimiters_and_terminal_punctuation(self):
        self.assertTrue(is_ordered_token_subsequence("x = 2", "Thus $x = 2$.") )

    def test_rejects_missing_or_extra_keys(self):
        response = json.dumps(
            {"ground_truths": {"a": "$x = 2$", "c": None}, "null_answer_reasons": {"c": "missing"}}
        )
        with self.assertRaisesRegex(ExtractionValidationError, "keys must be exactly"):
            parse_and_verify(response, self.solution, ["a", "b"])

    def test_rejects_empty_value(self):
        response = json.dumps({"ground_truths": {"a": ""}, "null_answer_reasons": {}})
        with self.assertRaisesRegex(ExtractionValidationError, "non-empty string or null"):
            parse_and_verify(response, self.solution, ["a"])

    def test_accepts_null_with_reason(self):
        response = json.dumps(
            {"ground_truths": {"a": None}, "null_answer_reasons": {"a": "Only an equation reference is given."}}
        )
        self.assertEqual(
            parse_and_verify(response, self.solution, ["a"]),
            ({"a": None}, {"a": "Only an equation reference is given."}),
        )

    def test_rejects_null_without_matching_reason(self):
        response = json.dumps({"ground_truths": {"a": None}, "null_answer_reasons": {}})
        with self.assertRaisesRegex(ExtractionValidationError, "null-answer keys"):
            parse_and_verify(response, self.solution, ["a"])

    def test_rejects_non_json(self):
        with self.assertRaisesRegex(ExtractionValidationError, "not JSON"):
            parse_and_verify("```json", self.solution, ["a"])


class OutputColumnTest(unittest.TestCase):
    def test_extraction_uses_ground_truths_column_and_discards_final_answers(self):
        class Result:
            text = '{"ground_truths":{"a":"$x = 2$."},"null_answer_reasons":{}}'

        class Client:
            model = "gpt-5.5"
            model_reasoning_effort = "high"

            def complete(self, *args, **kwargs):
                return Result()

        row = {
            "id": "example",
            "question": "Find x.",
            "solution": "Thus $x = 2$.",
            "is_multi_part": False,
            "final_answers": "untrusted",
        }
        _, output = extract_one(
            0,
            row,
            Client(),
            Config("prompt", None, 1),
        )
        self.assertEqual(output["ground_truths"], {"a": "$x = 2$."})
        self.assertEqual(output["null_answer_reasons"], {})
        self.assertNotIn("final_answers", output)
        self.assertNotIn("extracted_ground_truths", output)


class SidecarRecordTest(unittest.TestCase):
    def test_sub_questions_and_null_answer_record(self):
        question = "Context. (a) Find x. (b) Find y."
        self.assertEqual(sub_questions(question, ["a", "b"]), {"a": "Find x.", "b": "Find y."})
        rows = [
            {
                "id": "sample/1",
                "source_file": "source.jsonl",
                "question": question,
                "solution": "No result for x. y = 2.",
                "is_multi_part": True,
                "ground_truths": {"a": None, "b": "y = 2."},
                "null_answer_reasons": {"a": "No final value is supplied."},
            }
        ]
        null_answers = collect_null_answers(Path("test.parquet"), rows)
        self.assertEqual(len(null_answers), 1)
        self.assertEqual(null_answers[0]["sub_part"], "a")
        self.assertEqual(null_answers[0]["sub_question"], "Find x.")

    def test_exhausted_row_raises_after_three_attempts_and_has_failure_record(self):
        class Result:
            text = '{"ground_truths":{"a":"invented = 99"},"null_answer_reasons":{}}'

        class Client:
            model = "gpt-5.5"
            model_reasoning_effort = "high"

            def __init__(self):
                self.calls = 0

            def complete(self, *args, **kwargs):
                self.calls += 1
                return Result()

        client = Client()
        row = {
            "id": "bad/1",
            "source_file": "source.jsonl",
            "question": "Find x.",
            "solution": "x = 2.",
            "is_multi_part": False,
        }
        with self.assertRaises(RowExtractionError) as caught:
            extract_one(4, row, client, Config("prompt", None, 3))
        self.assertEqual(client.calls, 3)
        record = failed_row_record(Path("test.parquet"), caught.exception)
        self.assertEqual(record["sample_id"], "bad/1")
        self.assertEqual(record["attempts"], 3)
        self.assertEqual(len(record["errors"]), 3)


if __name__ == "__main__":
    unittest.main()
