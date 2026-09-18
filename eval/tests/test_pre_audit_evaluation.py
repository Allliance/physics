import unittest
from unittest.mock import patch

from eval.pre_audit import DATASETS, load_benchmark


class PreAuditEvaluationTests(unittest.TestCase):
    def test_original_selections_and_counts(self):
        expected = {
            "phybench": 100,
            "hle-physics": 202,
            "prism": 100,
            "ugphysics": 100,
            "cmt": 50,
            "critpt": 55,
        }
        for name in DATASETS:
            with self.subTest(name=name):
                pipeline = load_benchmark(name)
                self.assertEqual(len(pipeline.problems), expected[name])
                self.assertIs(pipeline.questions, pipeline.problems)
                self.assertEqual(len({problem.id for problem in pipeline.problems}), expected[name])
                self.assertTrue(all(problem.question and problem.reference_answer
                                    for problem in pipeline.problems))
        self.assertEqual(len(load_benchmark("critpt").metadata["excluded_ids"]), 16)

    def test_aliases(self):
        self.assertEqual(load_benchmark("HLE").dataset, "hle-physics")
        self.assertEqual(load_benchmark("CMT-Benchmark").dataset, "cmt")

    def test_public_problem_does_not_put_reference_in_prompt(self):
        for name in DATASETS:
            problem = load_benchmark(name).problems[0]
            exported = problem.as_dict(include_reference=False)
            self.assertNotIn("reference_answer", exported)
            self.assertNotIn("native", exported)
            self.assertNotIn("reference_answer", problem.predictor_input())

    def test_hle_adapted_datasets_use_injected_judge(self):
        calls = []

        def judge(problem, response):
            calls.append((problem.id, response, problem.reference_answer))
            return {"judgment": {"correct": "yes"}, "source": "test"}

        for name in ("hle-physics", "cmt", "critpt"):
            with self.subTest(name=name):
                pipeline = load_benchmark(name, judge=judge)
                problem = pipeline.problems[0]
                result = pipeline.evaluate(problem.id, "candidate")
                self.assertTrue(result.correct)
                self.assertEqual(result.score, 1.0)
        self.assertEqual(len(calls), 3)

    def test_phybench_parses_native_schema_before_original_scorer(self):
        pipeline = load_benchmark("phybench")
        problem = pipeline.problems[0]
        score = {"correct": True, "eed_score": 100.0, "grading_error": None}
        with patch("eval.pre_audit.native.grade_one", return_value=score) as grade:
            result = pipeline.evaluate(problem.id, '{"final_answer":"x"}')
        self.assertTrue(result.correct)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(grade.call_args.args[2], "x")

    def test_malformed_phybench_response_is_a_nonpass_without_scorer_call(self):
        pipeline = load_benchmark("phybench")
        result = pipeline.evaluate(pipeline.problems[0].id, "not json")
        self.assertFalse(result.correct)
        self.assertIn("answer_format_error", result.details)

    def test_prism_passes_raw_response_to_original_scorer(self):
        pipeline = load_benchmark("prism")
        problem = pipeline.problems[0]
        score = {"correct": False, "final_answer_score": 0.5, "grading_error": None}
        with patch("eval.pre_audit.native.grade_one", return_value=score) as grade:
            result = pipeline.evaluate(problem.id, "raw $$x=y$$")
        self.assertFalse(result.correct)
        self.assertEqual(result.score, 0.5)
        self.assertEqual(grade.call_args.args[2], "raw $$x=y$$")

    def test_ugphysics_runs_auxiliary_only_after_native_failure(self):
        judge_calls = []

        def judge(problem, response):
            judge_calls.append((problem.id, response))
            return {"correct": "yes"}

        pipeline = load_benchmark("ugphysics", judge=judge)
        problem = pipeline.problems[0]
        passed = {"correct": True, "grading_error": None}
        failed = {"correct": False, "grading_error": None}
        with patch("eval.pre_audit.native.grade_one", return_value=passed):
            self.assertTrue(pipeline.evaluate(problem.id, "answer").correct)
        self.assertEqual(judge_calls, [])
        with patch("eval.pre_audit.native.grade_one", return_value=failed):
            result = pipeline.evaluate(problem.id, "answer")
        self.assertTrue(result.correct)
        self.assertEqual(len(judge_calls), 1)
        self.assertIn("native", result.details)
        self.assertIn("auxiliary", result.details)

    def test_native_scorer_errors_are_not_counted_as_wrong(self):
        pipeline = load_benchmark("ugphysics", use_ugphysics_auxiliary=False)
        error = {"correct": False, "grading_error": "ImportError: missing dependency"}
        with patch("eval.pre_audit.native.grade_one", return_value=error):
            with self.assertRaisesRegex(RuntimeError, "native scorer failed"):
                pipeline.evaluate(pipeline.problems[0].id, "answer")

    def test_batch_denominator_validation(self):
        pipeline = load_benchmark("cmt", judge=lambda p, r: {"correct": "no"})
        with self.assertRaisesRegex(ValueError, "Missing cmt responses"):
            pipeline.evaluate_many({pipeline.problems[0].id: "answer"}, require_all=True)
        with self.assertRaisesRegex(ValueError, "Unknown cmt response IDs"):
            pipeline.evaluate_many({"missing": "answer"})


if __name__ == "__main__":
    unittest.main()
