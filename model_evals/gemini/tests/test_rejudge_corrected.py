import unittest
from types import SimpleNamespace

from model_evals.gemini.rejudge_corrected import compare, validate_completion


class CompareTests(unittest.TestCase):
    def test_recovered_transport_error_accepts_completed_turn(self):
        validate_completion(SimpleNamespace(text='{}', events=[
            {'type': 'error', 'message': 'Reconnecting'}, {'type': 'turn.completed'}]))

    def test_failed_or_unfinished_turn_is_not_a_judgment(self):
        for events in [[{'type': 'error'}], [{'type': 'turn.failed'}],
                       [{'type': 'turn.completed'}, {'type': 'turn.failed'}]]:
            with self.assertRaises(ValueError):
                validate_completion(SimpleNamespace(text='{}', events=events))

    def fixture(self):
        records, judgments = [], {}
        for qid, old, new in [('a', [1, 0, 0, 0], [0, 0, 0, 0]),
                              ('b', [0, 0, 0, 0], [1, 1, 0, 0])]:
            for number, (before, after) in enumerate(zip(old, new), 1):
                key = f'hle/{number}/{qid}'
                records.append({'key': key, 'benchmark': 'hle', 'id': qid, 'round': number,
                                'baseline': {'correct': 'yes' if before else 'no', 'reasoning': 'old'}})
                judgments[key] = {'judgment': {'correct': 'yes' if after else 'no', 'reasoning': 'new'}}
        return records, judgments

    def test_mean_and_pass_changes_and_bidirectional_flips(self):
        records, judgments = self.fixture()
        result = compare(records, judgments)
        row = result['results']['hle']
        self.assertTrue(result['complete'])
        self.assertEqual(row['mean_change_pp'], 12.5)
        self.assertEqual(row['pass_change_pp'], 0)
        self.assertEqual(row['fable_yes_sol_no'], 1)
        self.assertEqual(row['fable_no_sol_yes'], 2)
        self.assertEqual(len(result['disagreements']), 3)

    def test_missing_judgment_keeps_full_denominator_and_no_final_score(self):
        records, judgments = self.fixture()
        del judgments['hle/1/a']
        result = compare(records, judgments)
        row = result['results']['hle']
        self.assertFalse(result['complete'])
        self.assertEqual((row['questions'], row['attempts'], row['judged']), (2, 8, 7))
        self.assertNotIn('sol', row)
        self.assertNotIn('mean_change_pp', row)


if __name__ == '__main__':
    unittest.main()
