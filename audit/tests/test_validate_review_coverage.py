import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from process_audits import process_audits, read_audits, read_overrides
from validate_review_coverage import validate


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def check(self, labels, reviewers=None, override=None):
        rows = [dict(annotation_id=str(i), display_id='1', source_problem_id='q',
                     dataset='phybench', category='physics', **{'pass': str(i)},
                     label=label, note='one\r\ntwo', reviewer_id=(reviewers or ['a', 'b', 'c'])[i-1],
                     submitted_at='2026-09-08') for i, label in enumerate(labels, 1)]
        raw, processed, overrides = (self.root / n for n in ['raw.csv', 'processed.csv', 'overrides.json'])
        with raw.open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        overrides.write_text(json.dumps([] if override is None else [dict(
            dataset='phybench', source_problem_id='q', label=override)]))
        fields, loaded = read_audits(raw)
        output, _ = process_audits(loaded, fields, read_overrides(overrides))
        with processed.open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(output)
        return validate(raw, processed, overrides)

    def test_two_distinct_agreeing_reviewers_pass(self):
        self.assertTrue(self.check(['MODEL_FAILURE'] * 2)['passed'])

    def test_two_passes_by_same_reviewer_fail(self):
        report = self.check(['MODEL_FAILURE'] * 2, ['a', 'a'])
        self.assertEqual(report['summary']['missing_single_override'], 1)
        self.assertFalse(report['passed'])

    def test_single_requires_override(self):
        self.assertFalse(self.check(['MODEL_FAILURE'])['passed'])
        self.assertTrue(self.check(['MODEL_FAILURE'], override='MODEL_FAILURE')['passed'])

    def test_third_pass_majority_still_requires_override(self):
        labels = ['MODEL_FAILURE', 'GRADER_FAILURE', 'MODEL_FAILURE']
        report = self.check(labels)
        self.assertEqual(report['summary']['missing_conflict_override'], 1)
        self.assertFalse(report['passed'])
        self.assertTrue(self.check(labels, override='MODEL_FAILURE')['passed'])

    def test_disagreement_with_override_passes(self):
        self.assertTrue(self.check(['MODEL_FAILURE', 'GRADER_FAILURE'], override='PROBLEM_FAILURE')['passed'])

    def test_missing_reviewer_identity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'reviewer ID'):
            self.check(['MODEL_FAILURE'], [''])

    def test_processed_verdict_tampering_is_rejected(self):
        self.check(['MODEL_FAILURE'] * 2)
        p = self.root / 'processed.csv'
        p.write_text(p.read_text().replace('MODEL_FAILURE', 'GRADER_FAILURE'))
        with self.assertRaisesRegex(ValueError, 'do not reproduce'):
            validate(self.root/'raw.csv', p, self.root/'overrides.json')

    def test_embedded_newlines_reproduce(self):
        self.check(['MODEL_FAILURE'] * 2)
        p = self.root / 'processed.csv'
        p.write_text(p.read_text())
        self.assertTrue(validate(self.root/'raw.csv', p, self.root/'overrides.json')['passed'])


if __name__ == '__main__':
    unittest.main()
