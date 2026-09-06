"""Network-free CMT dataset, selection, resume, and scoring integration tests."""

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cmt_eval import dataset, runner, scoring


ROWS = [
    {"index": 0, "prompt": "Compute 2+2", "solution": "4", "type": "HF",
     "audit_summary": "PRIVATE AUDIT", "parameters": "PRIVATE PARAMETERS"},
    {"index": 1, "prompt": "Compute 3+3", "solution": "6", "type": "ED"},
]


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "data.json"

    def write(self, value):
        self.path.write_text(json.dumps(value))
        return self.path

    def test_references_and_audits_are_separated(self):
        questions, answers = dataset.load_dataset(self.write(ROWS))
        self.assertEqual(questions[0], {"id": "0", "question": "Compute 2+2", "category": "HF"})
        self.assertEqual(answers, {"0": "4", "1": "6"})

    def test_malformed_rows_and_duplicate_indices_are_rejected(self):
        for value in [{}, [], ["bad"], ROWS + [ROWS[0]],
                      [{**ROWS[0], "index": True}], [{**ROWS[0], "index": -1}],
                      [{**ROWS[0], "index": "0"}], [{**ROWS[0], "prompt": " "}],
                      [{**ROWS[0], "solution": None}], [{**ROWS[0], "type": 7}]]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                dataset.load_dataset(self.write(value))

    def test_integer_and_string_id_files(self):
        self.assertEqual(dataset.read_ids(self.write([0, "01"]), "--ids-file"), ["0", "1"])
        for value in [{"ids": [0]}, [True], [-1], [1.5], ["abc"], ["-1"]]:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "JSON list"):
                dataset.read_ids(self.write(value), "--ids-file")

    def test_category_and_exclusions_apply_before_limit(self):
        questions, _ = dataset.load_dataset(self.write(ROWS))
        self.assertEqual(dataset.select_questions(questions, category="hf"), questions[:1])
        selected = dataset.select_questions(questions, requested_ids=["0", "1"],
                                            excluded_ids=["0", "999"], max_samples=1)
        self.assertEqual(selected, questions[1:])
        with self.assertRaisesRegex(ValueError, "not found"):
            dataset.select_questions(questions, category="HF", requested_ids=["1"])

    def test_checked_in_dataset_loads(self):
        for name in ["cmt_data_clean.json", "cmt_data_original.jsonl"]:
            with self.subTest(name=name):
                questions, answers = dataset.load_dataset(runner.BENCHMARK_ROOT / "data" / name)
                self.assertTrue(questions)
                self.assertEqual({q["id"] for q in questions}, set(answers))

    def test_jsonl_matches_json_and_preserves_content(self):
        expected = dataset.load_dataset(self.write(ROWS))
        path = self.path.with_suffix(".jsonl")
        path.write_text("\n" + "\n\n".join(json.dumps(row) for row in ROWS) + "\n")
        self.assertEqual(dataset.load_dataset(path), expected)

    def test_invalid_jsonl_is_rejected(self):
        path = self.path.with_suffix(".jsonl")
        path.write_text(json.dumps(ROWS[0]) + "\n\ninvalid\n")
        with self.assertRaisesRegex(ValueError, r"Invalid JSONL at .*:3:"):
            dataset.load_dataset(path)
        for text in ["\n\n", "null\n", json.dumps(ROWS) + "\n",
                     "\n".join(json.dumps(ROWS[0]) for _ in range(2))]:
            path.write_text(text)
            with self.subTest(text=text), self.assertRaises(ValueError):
                dataset.load_dataset(path)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dataset = self.root / "data.json"
        self.dataset.write_text(json.dumps(ROWS))
        self.artifacts = self.root / "artifacts"
        self.output = self.artifacts / "run.json"
        self.args = ["--dataset", str(self.dataset), "--output", str(self.output),
                     "--num-workers", "1", "--fable-model", "claude-fable-5"]
        self.counts = {}

    def predict(self, q, image):
        self.assertEqual(set(q), {"id", "question", "category"})
        self.assertIsNone(image)
        qid = q["id"]
        self.counts[qid] = self.counts.get(qid, 0) + 1
        correct = (qid == "0" and self.counts[qid] == 1) or (qid == "1" and self.counts[qid] == 2)
        return {"response": "yes" if correct else "no"}

    def run_main(self, extra=(), predict=None, judge=None):
        with patch.object(runner, "ARTIFACT_ROOT", self.artifacts), \
                patch.object(runner, "BENCHMARK_ROOT", self.root), \
                patch.object(runner, "make_predictor", return_value=predict or self.predict) as predictions, \
                patch.object(scoring, "make_judge", return_value=judge or (lambda q, p, a: {"correct": p["response"]})) as judgments, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = runner.main(self.args + list(extra))
        return result, predictions, judgments

    def summary(self):
        return json.loads(self.output.with_suffix(".summary.json").read_text())

    def test_jsonl_evaluation_and_resume(self):
        path = self.dataset.with_suffix(".jsonl")
        path.write_text("\n".join(json.dumps(row) for row in ROWS) + "\n")
        extra = ["--dataset", str(path)]
        self.assertEqual(self.run_main(extra)[0], 0)
        self.assertEqual(self.summary()["dataset"], str(path))
        self.assertEqual(self.summary()["questions"], 2)
        result, predictions, judgments = self.run_main(extra)
        self.assertEqual(result, 0)
        predictions.assert_not_called()
        judgments.assert_not_called()

    def test_both_models_round_extension_and_reaggregation(self):
        for model in ["gpt-5.6-sol", "fable"]:
            with self.subTest(model=model):
                self.output = self.artifacts / f"{model}.json"
                self.counts = {}
                extra = ["--model", model, "--output", str(self.output)]
                self.assertEqual(self.run_main(extra)[0], 0)
                saved = self.output.read_bytes()
                self.assertEqual(self.run_main(extra + ["--rounds", "2"])[0], 0)
                self.assertEqual(saved, self.output.read_bytes())
                self.assertEqual(self.counts, {"0": 2, "1": 2})
                self.assertEqual(self.summary()["final_score"], 0.5)
                result, predictions, judgments = self.run_main(extra + ["--rounds", "2", "--aggregation", "max"])
                self.assertEqual(result, 0)
                predictions.assert_not_called()
                judgments.assert_not_called()
                self.assertEqual(self.summary()["final_score"], 1.0)
                self.assertEqual(self.run_main(extra)[0], 0)
                self.assertEqual(self.summary()["rounds"], 1)

    def test_generation_failure_retries_only_missing(self):
        def fail(q, image):
            if q["id"] == "1":
                raise RuntimeError("temporary failure")
            return {"response": "yes"}
        self.assertEqual(self.run_main(predict=fail)[0], 1)
        self.assertIsNone(self.summary()["final_score"])
        retry = MagicMock(return_value={"response": "no"})
        self.assertEqual(self.run_main(predict=retry)[0], 0)
        retry.assert_called_once()
        self.assertEqual(retry.call_args.args[0]["id"], "1")

    def test_judge_failure_retries_without_regeneration(self):
        def fail(q, p, a):
            if q["id"] == "1":
                raise RuntimeError("temporary failure")
            self.assertEqual(a, "4")
            return {"correct": "yes"}
        self.assertEqual(self.run_main(judge=fail)[0], 1)
        self.assertIsNone(self.summary()["final_score"])
        retry = MagicMock(return_value={"correct": "no"})
        result, predictions, _ = self.run_main(judge=retry)
        self.assertEqual(result, 0)
        predictions.assert_not_called()
        retry.assert_called_once()
        self.assertEqual(retry.call_args.args[2], "6")

    def test_dataset_changes_reject_resume_before_calls(self):
        self.run_main()
        summary_before = self.output.with_suffix(".summary.json").read_bytes()
        for field in ["prompt", "solution", "type"]:
            self.dataset.write_text(json.dumps([{**ROWS[0], field: "changed"}, ROWS[1]]))
            predict = MagicMock()
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "settings"):
                self.run_main(predict=predict)
            predict.assert_not_called()
        self.assertEqual(summary_before, self.output.with_suffix(".summary.json").read_bytes())

    def test_settings_changes_reject_resume(self):
        self.run_main()
        for extra in [["--reasoning-effort", "low"], ["--use-tools"], ["--model", "fable"],
                      ["--max-samples", "1"], ["--judge-reasoning-effort", "low"]]:
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "settings"):
                self.run_main(extra)

    def test_changed_prediction_rejects_judge_cache(self):
        self.run_main()
        predictions = json.loads(self.output.read_text())
        predictions["0"]["response"] = "changed"
        self.output.write_text(json.dumps(predictions))
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.run_main()

    def test_outputs_must_stay_in_artifacts(self):
        for output in [self.dataset, self.root / "elsewhere.json", self.artifacts / "bad.txt"]:
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "artifacts"):
                self.run_main(["--output", str(output)])
        self.assertFalse(self.artifacts.exists())

    def test_relative_output_uses_benchmark_directory(self):
        self.assertEqual(self.run_main(["--output", "artifacts/run.json"])[0], 0)
        self.assertTrue(self.output.exists())

    def test_list_categories_makes_no_calls_or_artifacts(self):
        result, predictions, judgments = self.run_main(["--list-categories"])
        self.assertEqual(result, 0)
        predictions.assert_not_called()
        judgments.assert_not_called()
        self.assertFalse(self.artifacts.exists())

    def test_exclusions_precede_limit_across_rounds(self):
        exclusions = self.root / "exclude.json"
        exclusions.write_text("[0]")
        self.assertEqual(self.run_main(["--exclude-ids-file", str(exclusions),
                                        "--max-samples", "1", "--rounds", "2"])[0], 0)
        self.assertEqual(self.counts, {"1": 2})

    def test_empty_prediction_is_pending(self):
        self.assertEqual(self.run_main(predict=lambda q, image: {"response": " "})[0], 1)
        self.assertEqual(self.summary()["missing_judgments"], 2)


if __name__ == "__main__":
    unittest.main()
