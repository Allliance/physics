import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'evaluate_initial.py'
spec = importlib.util.spec_from_file_location('fable_initial_test', MODULE)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class InitialEvaluationTests(unittest.TestCase):
    def test_phybench_final_answer_extraction_does_not_rewrite_expressions(self):
        expression = r'\frac{a+b}{c}'
        self.assertEqual(runner.parse_final_answer(json.dumps({'final_answer': expression})), expression)
        for invalid in ['not JSON', '[]', '{"final_answer": 2}', '{"answer": "x"}',
                        '{"final_answer": "x", "explanation": "extra"}']:
            with self.assertRaises(ValueError):
                runner.parse_final_answer(invalid)

    def test_phybench_nonpasses_do_not_require_auxiliary_judgments(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(output=Path(tmp), benchmark='phybench')
            rows = [{'id': 'a'}, {'id': 'b'}]
            config = {'judge_model': None, 'judge_reasoning_effort': None}
            for item_id, correct in [('a', True), ('b', False)]:
                runner.append(args.output / 'generations.jsonl', {'id': item_id})
                runner.append(args.output / 'scores.jsonl', {'id': item_id, 'correct': correct})
            self.assertTrue(runner.summarize(args, rows, config))
            summary = json.loads((args.output / 'summary.json').read_text())
            self.assertEqual(summary['initial_accuracy'], 0.5)
            self.assertEqual(summary['missing_auxiliary_ids'], [])

    def test_selection_keeps_all_original_items_including_audit_failures(self):
        ids = [str(i) for i in range(100)]
        rows = [{'problem_id': i, 'AI_audit': {'verdict': 'benchmark_failure'}} for i in ids]
        manifest = {'benchmarks': {'prism': {'selected_problem_ids': ids}}}
        self.assertEqual(runner.validate_selection(rows, manifest, 'prism'), ids)
        for invalid in [rows[:-1], rows[::-1], rows[:-1] + [rows[0]]]:
            with self.assertRaises(ValueError):
                runner.validate_selection(invalid, manifest, 'prism')

    def test_resume_rejects_changed_model_prompt_or_judge(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'manifest.json'
            config = {'model': 'claude-fable-5', 'sample_sha256': 'original', 'judge_model': 'gpt-5.6-sol'}
            runner.check_checkpoint(path, config)
            runner.check_checkpoint(path, config)
            for key in config:
                with self.assertRaises(ValueError):
                    runner.check_checkpoint(path, {**config, key: 'changed'})
            self.assertEqual(json.loads(path.read_text()), config)

    def test_partial_judging_does_not_report_complete_accuracy(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(output=Path(tmp), benchmark='ugphysics')
            rows = [{'id': 'a'}, {'id': 'b'}]
            config = {'judge_model': 'gpt-5.6-sol', 'judge_reasoning_effort': 'high'}
            for item_id in ['a', 'b']:
                runner.append(args.output / 'generations.jsonl', {'id': item_id})
            runner.append(args.output / 'scores.jsonl', {'id': 'a', 'correct': True})
            runner.append(args.output / 'scores.jsonl', {'id': 'b', 'correct': False})
            self.assertFalse(runner.summarize(args, rows, config))
            summary = json.loads((args.output / 'summary.json').read_text())
            self.assertIsNone(summary['initial_accuracy'])
            runner.append(args.output / 'auxiliary_judgments.jsonl', {'id': 'b', 'correct': True})
            self.assertTrue(runner.summarize(args, rows, config))
            summary = json.loads((args.output / 'summary.json').read_text())
            self.assertEqual(summary['initial_accuracy'], 1)
            self.assertEqual(summary['rule_correct'], 1)


if __name__ == '__main__':
    unittest.main()
