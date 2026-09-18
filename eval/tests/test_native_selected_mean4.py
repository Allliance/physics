import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from eval.reproduction import native_selected_mean4 as runner


class NativeSelectedTests(unittest.TestCase):
    def test_predictor_receives_only_native_prompt(self):
        row = {'id': 'a', 'system_prompt': 'native system', 'prompt': 'native question',
               'native': {'solution': 'SECRET', 'answers': 'SECRET'}, 'reference_answer': 'SECRET'}
        self.assertEqual(runner.predictor_input(row), {
            'id': 'a', 'system_prompt': 'native system', 'prompt': 'native question'})

    def test_gemini_uses_native_prompt_schema_and_no_tools(self):
        row = {'id': 'a', 'system_prompt': 'native system', 'prompt': 'native question'}
        config = {'model': 'gemini-3.1-pro-preview', 'max_output_tokens': 65536,
                  'answer_schema': {'type': 'object'}}
        with patch.object(runner, 'generate_gemini', return_value={
                'response': '{"final_answer":"x"}', 'tool_events': [], 'refused': False}) as call:
            result = runner.generate_one(row, config, 1800)
        self.assertEqual(result['final_answer'], 'x')
        self.assertEqual(call.call_args.args, ('native question',))
        self.assertEqual(call.call_args.kwargs['system_prompt'], 'native system')
        self.assertEqual(call.call_args.kwargs['output_schema'], config['answer_schema'])
        self.assertFalse(call.call_args.kwargs['use_tools'])
        self.assertFalse(call.call_args.kwargs['web_search'])

    def test_malformed_completed_answer_is_retained(self):
        with patch.object(runner, 'generate_gemini', return_value={
                'response': 'malformed JSON', 'tool_events': [], 'refused': False}) as call:
            result = runner.generate_one({'id': 'a', 'prompt': 'Q', 'system_prompt': 'S'},
                {'model': 'gemini-3.1-pro-preview', 'max_output_tokens': 65536, 'answer_schema': {}}, 1800)
        self.assertEqual(result['response'], 'malformed JSON')
        self.assertEqual(result['final_answer'], '')
        self.assertTrue(result['answer_format_error'])
        self.assertEqual(call.call_count, 1)

    def test_scoring_preserves_native_response_formats(self):
        for benchmark, prediction, expected in (
            ('phybench', {'response': '{"final_answer":"x"}', 'final_answer': 'x'}, 'x'),
            ('prism', {'response': '$$x=y$$'}, '$$x=y$$'),
            ('ugphysics', {'response': r'\boxed{x}'}, r'\boxed{x}')):
            with patch.object(runner.native_base, 'grade_one', return_value={'correct': True}) as call:
                runner.native_score(benchmark, {'_eval_id': 'a'}, prediction, 180)
            self.assertEqual(call.call_args.args[2], expected)

    def test_pending_auxiliary_cannot_shrink_denominator(self):
        scores = {'a': {'correct': True}, 'b': {'correct': False}}
        result = runner.summarize(['a', 'b'], {'a': {}, 'b': {}}, scores, {}, 'ugphysics')
        self.assertFalse(result['complete'])
        self.assertIsNone(result['accuracy'])
        result = runner.summarize(['a', 'b'], {'a': {}, 'b': {}}, scores,
                                  {'b': {'correct': False}}, 'ugphysics')
        self.assertTrue(result['complete'])
        self.assertEqual(result['accuracy'], 0.5)

    def test_suite_requires_four_complete_attempts(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            for attempt in range(1, 4):
                p = output / 'gemini/phybench' / f'attempt-{attempt}'
                p.mkdir(parents=True)
                (p / 'summary.json').write_text(json.dumps({
                    'complete': True, 'generated': 100, 'native_scored': 100,
                    'auxiliary_judged': 0, 'auxiliary_added': 0, 'native_correct': 90,
                    'correct': 90, 'grading_errors': [], 'answer_format_errors': []}))
            result = runner.suite_report(output)['results']['gemini/phybench']
            self.assertEqual(result['generated'], 300)
            self.assertFalse(result['complete'])
            self.assertIsNone(result['mean_at_4_percent'])


if __name__ == '__main__':
    unittest.main()
