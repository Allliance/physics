import unittest
from pathlib import Path

from eval.reproduction.selected_mean4 import aggregate, commands, MODELS
from eval.storage import fingerprint


class SelectedMean4Tests(unittest.TestCase):
    def attempt(self, grades):
        predictions = {qid: {'response': 'answer', 'tool_events': []} for qid in grades}
        judgments = {qid: {
            'prediction_sha256': fingerprint(predictions[qid]),
            'judgment': {'correct': 'yes' if grade else 'no', 'strict': True,
                         'confidence': 100, 'reasoning': 'checked',
                         'extracted_final_answer': 'answer'}} for qid, grade in grades.items()}
        return predictions, judgments

    def test_mean_is_not_pass_at_four(self):
        rows = [{'id': 'a'}, {'id': 'b'}]
        attempts = [self.attempt({'a': 1, 'b': 0}), self.attempt({'a': 0, 'b': 1}),
                    self.attempt({'a': 0, 'b': 1}), self.attempt({'a': 0, 'b': 1})]
        result = aggregate(rows, attempts)
        self.assertTrue(result['complete'])
        self.assertEqual(result['mean_at_4'], 0.5)
        self.assertEqual([r['mean_at_4'] for r in result['per_question']], [0.25, 0.75])

    def test_missing_grade_preserves_denominator(self):
        attempts = [self.attempt({'a': 1}) for _ in range(3)] + [({}, {})]
        result = aggregate([{'id': 'a'}], attempts)
        self.assertFalse(result['complete'])
        self.assertIsNone(result['mean_at_4'])
        self.assertEqual(result['expected_answers'], 4)
        with self.assertRaises(ValueError):
            aggregate([{'id': 'a'}], attempts[:3])

    def test_changed_prediction_rejected(self):
        attempts = [self.attempt({'a': 1}) for _ in range(4)]
        attempts[0][0]['a']['response'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'changed'):
            aggregate([{'id': 'a'}], attempts)

    def test_wrong_ids_and_tool_events_rejected(self):
        with self.assertRaisesRegex(ValueError, 'IDs'):
            aggregate([{'id': 'a'}], [self.attempt({'b': 1}) for _ in range(4)])
        attempts = [self.attempt({'a': 1}) for _ in range(4)]
        attempts[0][0]['a']['tool_events'] = [{'type': 'command_execution'}]
        with self.assertRaisesRegex(ValueError, 'no-tool'):
            aggregate([{'id': 'a'}], attempts)

    def test_commands_use_four_fresh_runs_and_requested_judges(self):
        jobs = commands(Path('/tmp/mean4'), 8)
        self.assertEqual(len(jobs), 36)
        self.assertEqual(len({cmd[cmd.index('--output') + 1] for cmd in jobs.values()}), 36)
        for name, cmd in jobs.items():
            model = name.split('/')[0]
            self.assertEqual(cmd[cmd.index('--model') + 1], MODELS[model][0])
            self.assertEqual(cmd[cmd.index('--judge-model') + 1], MODELS[model][1])
            self.assertIn('eval/data/pre_audit', cmd[cmd.index('--data') + 1])
            self.assertEqual(cmd[cmd.index('--mode') + 1], 'merged')


if __name__ == '__main__':
    unittest.main()
