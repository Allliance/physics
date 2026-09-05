import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "process_audits.py"
SPEC = importlib.util.spec_from_file_location("process_audits", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
FIELDS = [
    "annotation_id", "display_id", "source_problem_id", "dataset",
    "category", "pass", "label", "note",
]


def row(pass_number, label="MODEL_FAILURE", note="", problem="q1", dataset="test"):
    return dict(zip(FIELDS, [
        f"{dataset}-{problem}-{pass_number}", "1", problem, dataset,
        "physics", str(pass_number), label, note,
    ]))


class ProcessAuditsTests(unittest.TestCase):
    def process(self, rows, overrides=None):
        return audit.process_audits(rows, FIELDS, overrides or {})

    def test_matching_passes_prefer_longer_note_then_first_recorded(self):
        for notes, expected_pass in [(('short', 'longer'), '2'), (('equal', 'equal'), '1')]:
            with self.subTest(notes=notes):
                output, report = self.process([row(1, note=notes[0]), row(2, note=notes[1])])
                self.assertEqual(output[0]['pass'], expected_pass)
                self.assertEqual(len(output), 1)
                self.assertEqual(report['conflicts'], [])
        output, _ = self.process([row(2, note='equal'), row(1, note='equal')])
        self.assertEqual(output[0]['pass'], '2')

    def test_pass_three_matching_either_label_selects_longest_matching_note(self):
        for matching_pass in (1, 2):
            for third_note, expected_pass in [('tiny', str(matching_pass)), ('much longer note', '3')]:
                with self.subTest(matching_pass=matching_pass, third_note=third_note):
                    rows = [row(1, 'MODEL_FAILURE', 'long note'), row(2, 'PROBLEM_FAILURE', 'long note')]
                    rows.append(row(3, rows[matching_pass - 1]['label'], third_note))
                    output, report = self.process(rows)
                    self.assertEqual(len(output), 1)
                    self.assertEqual(output[0]['pass'], expected_pass)
                    self.assertEqual(report['conflicts'], [])

    def test_pass_three_matching_label_uses_first_recorded_on_tie(self):
        rows = [row(3, note='same'), row(2, 'PROBLEM_FAILURE'), row(1, note='same')]
        output, _ = self.process(rows)
        self.assertEqual(output, [rows[0]])

    def test_pass_three_only_adjudicates_disagreements(self):
        rows = [row(1, note='winner'), row(2), row(3, 'PROBLEM_FAILURE', 'much longer note')]
        output, report = self.process(rows)
        self.assertEqual(output, [rows[0]])
        self.assertEqual(report['conflicts'], [])

    def test_missing_or_distinct_third_pass_retains_every_audit(self):
        for third in ([], [row(3, 'GRADER_FAILURE')]):
            rows = [row(1), row(2, 'PROBLEM_FAILURE')] + third
            with self.subTest(third=third):
                output, report = self.process(rows)
                self.assertEqual(output, rows)
                self.assertEqual(report['summary']['unresolved_conflicts'], 1)
                self.assertEqual(report['conflicts'][0]['audits'], rows)

    def test_overrides_resolve_and_sort_conflicts_last(self):
        rows = [row(1), row(2, 'PROBLEM_FAILURE'), row(1, problem='q2'), row(2, 'PROBLEM_FAILURE', problem='q2')]
        override = {'dataset': 'test', 'source_problem_id': 'q1', 'label': 'PROBLEM_FAILURE', 'note': 'Reviewed'}
        output, report = self.process(rows, {('test', 'q1'): override})
        self.assertEqual(len(output), 3)
        self.assertEqual(output[0]['label'], 'PROBLEM_FAILURE')
        self.assertEqual(output[0]['note'], 'Reviewed')
        self.assertEqual([c['status'] for c in report['conflicts']], ['unresolved', 'resolved'])
        self.assertEqual(report['conflicts'][1]['override'], override)
        self.assertEqual(report['summary']['unresolved_conflicts'], 1)
        self.assertEqual(report['summary']['resolved_conflicts'], 1)

    def test_override_note_defaults_and_novel_label(self):
        rows = [row(1, note='original'), row(2, 'PROBLEM_FAILURE', 'different')]
        for label, expected_note in [('MODEL_FAILURE', 'original'), ('GRADER_FAILURE', '')]:
            with self.subTest(label=label):
                output, _ = self.process(rows, {('test', 'q1'): {'label': label}})
                self.assertEqual(output[0]['label'], label)
                self.assertEqual(output[0]['note'], expected_note)

    def test_singletons_and_dataset_identity(self):
        rows = [row(1), row(2, 'PROBLEM_FAILURE', dataset='other')]
        output, report = self.process(rows)
        self.assertEqual(output, rows)
        self.assertEqual(report['summary']['problems'], 2)

    def test_missing_early_passes_and_duplicate_pass(self):
        output, report = self.process([row(2), row(3, 'PROBLEM_FAILURE')])
        self.assertEqual(len(output), 2)
        self.assertEqual(report['summary']['unresolved_conflicts'], 1)
        with self.assertRaisesRegex(ValueError, 'same pass'):
            self.process([row(1), row(1)])

    def test_override_file_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'overrides.json'
            self.assertEqual(audit.read_overrides(path), {})
            path.write_text('')
            self.assertEqual(audit.read_overrides(path), {})
            entry = {'dataset': 'test', 'source_problem_id': 'q1', 'label': 'MODEL_FAILURE'}
            path.write_text(json.dumps([entry]))
            self.assertEqual(audit.read_overrides(path), {('test', 'q1'): entry})
            for invalid in [{}, [entry, entry], [{'label': 'MODEL_FAILURE'}], [dict(entry, label='TYPO')]]:
                path.write_text(json.dumps(invalid))
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    audit.read_overrides(path)

    def test_cli_removes_six_columns_preserves_input_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, conflicts, overrides = [root / name for name in (
                'audits.csv', 'audits_processed.csv', 'conflicts.json', 'audit-overrides.json',
            )]
            fields = FIELDS + sorted(audit.DROP_COLUMNS)
            rows = [row(1, note='Unicode α, quoted "text"\nand newline'), row(2, 'PROBLEM_FAILURE')]
            with source.open('w', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(dict(record, **{field: 'private' for field in audit.DROP_COLUMNS}) for record in rows)
            original = source.read_bytes()
            command = [sys.executable, str(SCRIPT), '--input', str(source), '--output', str(output),
                       '--conflicts', str(conflicts), '--overrides', str(overrides)]
            result = subprocess.run(command, check=True, capture_output=True, text=True, cwd=root)
            self.assertIn('Manual review needed: 1 problems', result.stdout)
            self.assertEqual(source.read_bytes(), original)
            with output.open(newline='') as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, FIELDS)
                self.assertEqual(list(reader), rows)
            self.assertNotIn('private', conflicts.read_text())
            generated = (output.read_bytes(), conflicts.read_bytes())
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual((output.read_bytes(), conflicts.read_bytes()), generated)
            command[command.index('--output') + 1] = str(source)
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(source.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
