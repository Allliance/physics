import argparse
import json
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from model_evals.gemini import evaluate_initial as runner


class InitialTests(unittest.TestCase):
    def test_actual_prism_prepare_isolates_native_utils_after_backend_import(self):
        python = runner.ROOT / 'model_evals/fable/.venv/bin/python'
        if not python.exists():
            self.skipTest('Native PRISM dependency environment is not installed')
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([str(python), str(Path(runner.__file__)), 'prism',
                                     '--stage', 'prepare', '--output', tmp],
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((Path(tmp) / 'manifest.json').read_text())
            self.assertEqual(manifest['problem_count'], 100)

    def test_scopes_preserve_selected_failures_and_reject_missing_questions(self):
        selected, sol, full = ['a', 'b'], ['a', 'b', 'c'], ['a', 'b', 'c', 'd']
        for name, expected in [('selected', selected), ('sol', sol), ('full', full)]:
            self.assertEqual(runner.select_ids(name, selected, sol, full), expected)
        with self.assertRaises(ValueError):
            runner.select_ids('sol', selected, ['a', 'c'], full)
        with self.assertRaises(ValueError):
            runner.select_ids('full', selected, sol, full + ['d'])

    def test_malformed_completed_phybench_answer_is_preserved_without_retry(self):
        generate = Mock(return_value={'response': 'not JSON', 'refused': False})
        config = {'max_output_tokens': 65536, 'answer_schema': {'type': 'object'}}
        row = {'id': 'a', 'prompt': 'question', 'system_prompt': 'system'}
        result = runner.generate_one(row, config, 10, generate)
        self.assertEqual(result['response'], 'not JSON')
        self.assertEqual(result['final_answer'], '')
        self.assertTrue(result['answer_format_error'])
        generate.assert_called_once()

    def test_generation_resume_never_resamples_a_completed_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(output=Path(tmp), benchmark='phybench', workers=1,
                                      limit=None, timeout=10)
            runner.append(args.output / 'generations.jsonl', {'id': 'a', 'response': 'wrong answer'})
            generate = Mock()
            runner.run_generation(args, [{'id': 'a'}], {}, generate)
            generate.assert_not_called()

    def test_export_keeps_exact_corrected_dataset_and_reuses_original_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(output=Path(tmp), benchmark='phybench')
            sample = [{'id': 'a', 'prompt': 'question', 'system_prompt': 'system'}]
            corrected = [{'id': 'a', 'question': 'question', 'reference_answer': 'reference'}]
            for name in ['manifest.json', 'sample.json']:
                (args.output / name).write_text('{}')
            record = {'id': 'a', 'response': '{"final_answer": "x"}', 'final_answer': 'x',
                      'requested_model': runner.MODEL, 'actual_model': runner.MODEL,
                      'tool_events': [], 'stop_reason': 'STOP',
                      'prompt_sha256': runner.fingerprint(['system', 'question'])}
            runner.append(args.output / 'generations.jsonl', record)
            with patch.object(runner, 'load_dataset', return_value=(corrected, {'dataset': 'phybench'})):
                runner.export_corrected(args, sample, {'scope': 'selected'})
                output = args.output / 'corrected-import'
                self.assertEqual(json.loads((output / 'dataset.json').read_text()), corrected)
                predictions = json.loads((output / 'predictions.json').read_text())
                self.assertEqual(predictions['a']['response'], 'x')
                self.assertEqual(predictions['a']['original_record_sha256'], runner.fingerprint(record))
                # Changed prompts cannot be passed off as matching generations.
                sample[0]['prompt'] = 'changed question'
                with self.assertRaises(ValueError):
                    runner.export_corrected(args, sample, {'scope': 'selected'})

    def test_truncated_generation_stays_pending_and_preserves_raw_evidence(self):
        from utils.gemini_backend import GeminiLimitError
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(output=Path(tmp), benchmark='prism', workers=1,
                                      limit=None, timeout=10)
            partial = {'response': '', 'refused': False, 'stop_reason': 'MAX_TOKENS'}
            generate = Mock(side_effect=GeminiLimitError('limit', partial))
            runner.run_generation(args, [{'id': 'a', 'prompt': 'question', 'system_prompt': 'system'}],
                                  {'max_output_tokens': 65536}, generate)
            self.assertFalse((args.output / 'generations.jsonl').exists())
            errors = runner.read_jsonl(args.output / 'errors.jsonl')
            self.assertEqual(errors[0]['partial_result'], partial)

    def test_incomplete_native_judging_does_not_publish_pass_at_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(output=Path(tmp), benchmark='ugphysics')
            runner.append(args.output / 'generations.jsonl', {'id': 'a'})
            runner.append(args.output / 'scores.jsonl', {'id': 'a', 'correct': False})
            config = {'scope': 'selected', 'judge_model': 'gpt-5.6-sol', 'judge_reasoning_effort': 'high'}
            self.assertFalse(runner.summarize(args, [{'id': 'a'}], config))
            summary = json.loads((args.output / 'summary.json').read_text())
            self.assertIsNone(summary['initial_accuracy'])
            self.assertEqual(summary['model'], runner.MODEL)


if __name__ == '__main__':
    unittest.main()
