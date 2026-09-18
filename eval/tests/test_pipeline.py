import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from eval.backends import validate_codex, validate_judgment
from eval.datasets import load_dataset, normalize, predictor_input
from eval.post_audit import parser, run
from eval.scoring import summarize


def judgment(correct='yes'):
    return {'extracted_final_answer': '2', 'reasoning': 'Equivalent.', 'correct': correct,
            'confidence': 100, 'strict': True}


class DatasetTests(unittest.TestCase):
    def test_formats(self):
        examples = [
            {'problem_id': 'a', 'problem_statement': 'Q', 'reference_solution': 'A', 'model_response': 'SECRET'},
            {'index': 0, 'prompt': 'Q', 'solution': 'A', 'type': 'HF'},
            {'challenge_id': 1, 'problem': 'Q', 'ground_truth': 'A'},
            {'id': 'hle', 'question': 'Q', 'answer': 'A'},
            {'_eval_id': 'UG/1', 'problem': 'Q', 'solution': 'S', 'answers': 'A'},
            {'id': 23, 'content': 'Q', 'solution': 'A'},
            {'id': 'generic', 'question': 'Q', 'reference_answer': 'A'},
        ]
        for example in examples:
            row = normalize(example, Path('.'))
            self.assertEqual(row['question'], 'Q')
            self.assertTrue(row['reference_answer'])
            self.assertEqual(set(predictor_input(row)), {'id', 'question'})
        self.assertEqual(normalize(examples[2], Path('.'))['id'], '01')

    def test_exclusions_and_missing_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            data = path / 'data.json'
            data.write_text(json.dumps([{'id': str(i), 'question': 'Q', 'reference_answer': 'A'} for i in range(4)]))
            rows, selection = load_dataset('custom', data=data)
            self.assertEqual(len(rows), 4)
            self.assertEqual(selection['excluded'], [])
            data.write_text(json.dumps([{'challenge_id': '01', 'problem': 'Q', 'ground_truth': None},
                                        {'challenge_id': '02', 'problem': 'Q', 'ground_truth': 'undefined'}]))
            rows, selection = load_dataset('critpt', data=data)
            self.assertEqual([r['id'] for r in rows], ['02'])
            self.assertEqual(selection['excluded'][0]['reason'], 'MISSING_REFERENCE')

    def test_duplicates_and_empty_references_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / 'data.json'
            row = {'id': '1', 'question': 'Q', 'answer': 'A'}
            data.write_text(json.dumps([row, row]))
            with self.assertRaisesRegex(ValueError, 'unique'):
                load_dataset('custom', data=data)
            with self.assertRaises(ValueError):
                normalize({**row, 'answer': ''}, data.parent)

    def test_actual_corrected_counts(self):
        for dataset, source_count, count in [
                ('phybench', 100, 87), ('prism', 100, 74), ('ugphysics', 100, 82),
                ('hle', 202, 116), ('cmt', 50, 49), ('critpt', 56, 54)]:
            rows, selection = load_dataset(dataset)
            self.assertEqual(len(rows), count)
            self.assertEqual(selection['source_count'], source_count)
            self.assertFalse(set(selection['retained_ids']) & {r['id'] for r in selection['excluded']})


class ScoringTests(unittest.TestCase):
    def test_incomplete_denominator_and_invalid_label(self):
        rows = [{'id': 'a'}, {'id': 'b'}]
        score = summarize(rows, {'a': {}, 'b': {}}, {'a': {'judgment': judgment()}})
        self.assertFalse(score['complete'])
        self.assertIsNone(score['accuracy'])
        self.assertEqual(score['missing_judgments'], 1)
        score = summarize(rows, {'a': {}, 'b': {}},
                          {'a': {'judgment': judgment()}, 'b': {'judgment': judgment('no')}})
        self.assertEqual(score['accuracy_percent'], 50)
        with self.assertRaises(ValueError):
            validate_judgment(judgment('maybe'))

    def test_codex_failed_stream_rejected(self):
        from types import SimpleNamespace
        for events in ([], [{'type': 'turn.failed'}], [{'type': 'turn.completed'}, {'type': 'error'}]):
            with self.assertRaises(ValueError):
                validate_codex(SimpleNamespace(text='2', events=events))
        validate_codex(SimpleNamespace(text='2', events=[{'type': 'turn.completed'}]))
        validate_codex(SimpleNamespace(
            text='2', events=[{'type': 'error'}, {'type': 'turn.completed'}]))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.data = self.path / 'data.json'
        self.data.write_text(json.dumps([{'id': str(i), 'question': f'Q{i}', 'answer': 'REFERENCE'} for i in range(2)]))
        self.argv = ['--dataset', 'custom', '--data', str(self.data), '--output', str(self.path / 'run')]

    def execute(self, extra=()):
        with contextlib.redirect_stdout(io.StringIO()):
            return run(parser().parse_args(self.argv + list(extra)))

    def test_fresh_resume_and_invalidation(self):
        seen = []

        def predict(row):
            seen.append(row)
            self.assertNotIn('reference_answer', row)
            return {'response': '2', 'refused': False}

        def judge(row, prediction):
            self.assertEqual(row['reference_answer'], 'REFERENCE')
            return {'judgment': judgment()}

        with patch('eval.post_audit.make_predictor', return_value=predict) as generation, patch(
                'eval.post_audit.make_judge', return_value=judge) as judging:
            self.assertEqual(self.execute(['--max-pending', '1']), 2)
            self.assertEqual(self.execute(), 0)
            self.assertEqual(len(seen), 2)
            generation.reset_mock()
            judging.reset_mock()
            self.assertEqual(self.execute(), 0)
            generation.assert_not_called()
            judging.assert_not_called()
        changed = json.loads(self.data.read_text())
        changed[0]['answer'] = 'DIFFERENT'
        self.data.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.execute()

    def test_prediction_edit_invalidates_judgment(self):
        with patch('eval.post_audit.make_predictor', return_value=lambda q: {'response': '2'}), patch(
                'eval.post_audit.make_judge', return_value=lambda q, p: {'judgment': judgment()}):
            self.execute()
        file = self.path / 'run/predictions.json'
        predictions = json.loads(file.read_text())
        predictions['0']['response'] = '3'
        file.write_text(json.dumps(predictions))
        with self.assertRaisesRegex(ValueError, 'Prediction changed'):
            self.execute()

    def test_failed_judgment_remains_pending_and_retries_once(self):
        attempts = {'0': 0, '1': 0}

        def judge(row, prediction):
            qid = row['id']
            attempts[qid] += 1
            if qid == '0' and attempts[qid] == 1:
                raise ValueError('Temporary request failure')
            return {'judgment': judgment()}

        with patch('eval.post_audit.make_predictor', return_value=lambda q: {'response': '2'}) as predict, patch(
                'eval.post_audit.make_judge', return_value=judge), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.execute(), 2)
            summary = json.loads((self.path / 'run/summary.json').read_text())
            self.assertIsNone(summary['accuracy'])
            self.assertEqual(summary['questions'], 2)
            predict.reset_mock()
            self.assertEqual(self.execute(), 0)
            predict.assert_not_called()
        self.assertEqual(attempts, {'0': 2, '1': 1})
        self.assertEqual(len((self.path / 'run/errors.jsonl').read_text().splitlines()), 1)

    def test_dry_run_has_no_writes_or_calls(self):
        with patch('eval.post_audit.make_predictor') as predict, patch('eval.post_audit.make_judge') as judge:
            self.assertEqual(self.execute(['--dry-run']), 0)
            self.assertFalse((self.path / 'run').exists())
            predict.assert_not_called()
            judge.assert_not_called()

if __name__ == '__main__':
    unittest.main()
