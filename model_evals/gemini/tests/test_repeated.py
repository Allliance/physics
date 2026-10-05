"""Network-free checks for Gemini dispatch and repeated benchmark protocols."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
for directory in (ROOT, ROOT / "benchmarks/hle", ROOT / "analysis/CMT-Benchmark",
                  ROOT / "analysis/CritPt/scripts"):
    sys.path.insert(0, str(directory))

from hle_eval import runner as hle, backends as hle_backend
from cmt_eval import runner as cmt, backends as cmt_backend
from critpt_eval import runner as critpt, backends as critpt_backend
from utils.gemini_backend import GeminiLimitError
from model_evals.gemini import repeated


class GeminiDispatchTests(unittest.TestCase):
    def test_gemini_keeps_sol_judge_and_prompts(self):
        for runner, backend in ((hle, hle_backend), (cmt, cmt_backend)):
            with self.subTest(runner=runner.__name__):
                args = runner.parse_args(["--model", "gemini", "--use-tools"])
                self.assertEqual(args.judge_model, "claude-fable-5")
                self.assertEqual(args.max_output_tokens, 65536)
                with patch("utils.gemini_backend.generate", return_value={"response": "4"}) as generate:
                    backend.make_predictor(args, args.model)({"question": "2+2", "answer": "SECRET"}, None)
                self.assertEqual(generate.call_args.args, ("2+2", None))
                self.assertEqual(generate.call_args.kwargs["system_prompt"], backend.TOOLS_SYSTEM_PROMPT)
                self.assertTrue(generate.call_args.kwargs["use_tools"])
                self.assertTrue(generate.call_args.kwargs["web_search"])

    def test_critpt_max_and_limits(self):
        args = critpt.parse_args(["--model", "gemini", "--reasoning-effort", "max", "--use-tools"])
        self.assertEqual(args.judge_model, "claude-fable-5")
        with patch("gemini_backend.generate", return_value={"response": "4"}) as generate:
            critpt_backend.make_predictor(args, {})({"question": "2+2"})
        self.assertEqual(generate.call_args.kwargs["effort"], "max")
        self.assertEqual(generate.call_args.kwargs["system_prompt"], critpt_backend.PREDICTION_TOOLS)

    def test_gemini_limit_reaches_hle_limit_policy(self):
        from hle_eval.errors import GenerationLimitError

        args = hle.parse_args(["--model", "gemini", "--limit-policy", "incorrect"])
        with patch("utils.gemini_backend.generate", side_effect=GeminiLimitError("budget", {})):
            with self.assertRaises(GenerationLimitError):
                hle_backend.make_predictor(args, args.model)({"question": "2+2"}, None)

    def test_corrected_hle_uses_saved_attempts_and_full_references(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            repeated.write_json(directory / "hle-corrected.json", [
                {"id": "x", "question": "2+2", "answer": "Full reference rationale", "category": "Physics", "image": ""}])
            output = directory / "hle-original-no-tools.json"
            repeated.write_json(output, {"x": {"response": "saved answer"}, "excluded": {"response": "ignore"}})
            job = {"output": str(output), "command": ["python", "-u", "evaluate.py", "--model", "gemini"]}
            with patch("hle_eval.scoring.judge_round", return_value={}) as judge:
                repeated.judge_hle_corrected(directory, job)
            populated = [call for call in judge.call_args_list if call.args[3]]
            self.assertEqual(len(populated), 1)
            self.assertEqual(populated[0].args[2], {"x": "Full reference rationale"})
            self.assertEqual(populated[0].args[3], {"x": {"response": "saved answer"}})
            self.assertIn("corrected", populated[0].args[4].name)

    def test_local_hle_never_sends_answers_to_predictor(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rows.json"
            path.write_text(json.dumps([{"id": "x", "question": "2+2", "answer": "4", "category": "Physics"}]))
            questions, _ = hle.load_questions(str(path), "Physics")
            self.assertNotIn("answer", questions[0])
            self.assertEqual(hle.load_answers(str(path), ["x"]), {"x": "4"})

    def test_incomplete_repeated_metrics_are_not_reported(self):
        row = repeated.metrics({"complete": False, "mean_score": .8, "max_score": 1}, 4)
        self.assertIsNone(row["mean@4"])
        self.assertIsNone(row["pass@4"])
        self.assertEqual(row["missing_judgments"], 16)

    def test_saved_judge_budget_survives_resume_without_hiding_other_changes(self):
        old = {'jobs': {'critpt': {'command': ['python', '--judge-max-output-tokens', '32768']}}}
        plan = {'jobs': {'critpt': {'command': ['python']}}}
        repeated.retain_judge_budgets(plan, old)
        self.assertEqual(repeated.semantic_plan(plan), repeated.semantic_plan(old))
        plan['jobs']['critpt']['command'][0] = 'different-python'
        self.assertNotEqual(repeated.semantic_plan(plan), repeated.semantic_plan(old))

    def test_disabled_jobs_stay_excluded_when_resuming_old_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            plan = {'jobs': {'hle-original-no-tools': {'question_ids': ['a', 'b']},
                             'hle-original-tools': {'question_ids': ['a', 'b']}},
                    'prediction_calls': 16}
            repeated.write_json(directory / 'disabled-jobs.json', {'jobs': ['hle-original-no-tools']})
            active = repeated.enabled_plan(directory, plan)
            self.assertEqual(list(active['jobs']), ['hle-original-tools'])
            self.assertEqual(active['prediction_calls'], 8)
            self.assertEqual(len(plan['jobs']), 2)


if __name__ == "__main__":
    unittest.main()
