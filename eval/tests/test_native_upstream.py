"""Verify upstream provenance, retained compatibility, and real native grading."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from eval.pre_audit import native
from eval.storage import require_checkpoint


class NativeUpstreamTests(unittest.TestCase):
    def test_provenance_pins_sources_and_invalidates_changed_checkpoints(self):
        for name, repository in native.REPOSITORIES.items():
            with self.subTest(name=name):
                source = native.provenance(name)
                self.assertEqual(source['repository'], repository)
                self.assertEqual(len(source['commit']), 40)
                self.assertTrue(source['sources_sha256'])
                self.assertTrue(all('_changed' not in path for path in source['sources_sha256']))
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'manifest.json'
                    require_checkpoint(path, source)
                    require_checkpoint(path, source)
                    with self.assertRaisesRegex(ValueError, 'Inputs/configuration changed'):
                        require_checkpoint(path, {**source, 'commit': 'different'})

    def test_missing_checkout_explains_submodule_initialization(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(native, 'ROOT', Path(directory)):
            for name in native.REPOSITORIES:
                with self.subTest(name=name), self.assertRaisesRegex(FileNotFoundError, 'git submodule update'):
                    native.provenance(name)

    def test_final_answer_policy_requires_all_final_nodes_and_preserves_fallback(self):
        row = {'grading_standard': [{'index': 7, 'is_final_answer': True},
                                    {'index': 12, 'is_final_answer': True}]}
        # Upstream matches identify list positions, rather than node IDs.
        partial = native.final_answer_result(row, [{'index_std': 0}])
        self.assertFalse(partial['correct'])
        self.assertEqual(partial['final_answer_score'], 0.5)
        self.assertTrue(native.final_answer_result(row, [{'index_std': 0}, {'index_std': 1}])['correct'])
        row['grading_standard'] = [{'index': 7}, {'index': 12}]
        self.assertTrue(native.final_answer_result(row, [{'index_std': 1}])['correct'])
        self.assertFalse(native.final_answer_result({'grading_standard': []}, [])['correct'])

    def test_nested_presentation_macros_and_unbalanced_input(self):
        for wrapped in (r'\boxed{v=\frac{2GM}{R}}', r'\fbox{v=\frac{2GM}{R}}',
                        r'\boxed{\fbox{v=\frac{2GM}{R}}}'):
            self.assertEqual(native.unwrap_presentation_macros(wrapped), r'v=\frac{2GM}{R}')
        self.assertEqual(native.unwrap_presentation_macros(r'\boxed{x=a}+\fbox{y=b}'), 'x=a+y=b')
        self.assertEqual(native.unwrap_presentation_macros(r'\boxed{x=a'), r'\boxed{x=a')
        self.assertEqual(native.normalize_latex(r'$$\left(x+1\right)$$'), '(x+1)')

    def test_real_scorers_accept_correct_and_reject_wrong_answers_without_import_leaks(self):
        python = native.ROOT / 'model_evals/fable/.venv/bin/python'
        if not python.exists():
            self.skipTest('Native scorer dependency environment is not installed')
        script = r'''
import json, sys
from eval.pre_audit import native
from utils import fable_backend
parent_utils = sys.modules['utils']
rows = {
    'phybench': {'_eval_id': 'test', 'id': 'test', 'tag': 'test', 'answer': 'x'},
    'prism': {'_eval_id': 'test', 'id': 'test', 'grading_standard': [
        {'index': 7, 'formula': 'x=2', 'dependency': [], 'is_final_answer': True}]},
    'ugphysics': {'_eval_id': 'test', 'answers': r'\boxed{2}',
                  'problem': 'What is one plus one?', 'solution': 'It is two.'},
}
answers = {'phybench': ('$$x$$', 'y'), 'prism': (r'$$\boxed{x=2}$$', '$$x=3$$'),
           'ugphysics': (r'\boxed{2}', r'\boxed{3}')}
results = {}
for name, row in rows.items():
    results[name] = [native.grade_one(name, row, text, 45) for text in answers[name]]
assert sys.modules['utils'] is parent_utils
assert sys.modules['utils.fable_backend'] is fable_backend
assert native.auxiliary_prompt(rows['ugphysics'], 'no boxed answer', 45) is None
prompt = native.auxiliary_prompt(rows['ugphysics'], r'\boxed{2}', 45)
expected = (native.JUDGE_PROMPT_PATH.read_text().replace('{{problem}}', 'What is one plus one?')
            .replace('{{RS}}', 'It is two.').replace('{{RA}}', '2')
            .replace('{{SS}}', r'\boxed{2}').replace('{{SA}}', '2'))
assert prompt == expected
print(json.dumps(results))
'''
        result = subprocess.run([str(python), '-c', script], cwd=native.ROOT,
                                capture_output=True, text=True, timeout=240)
        self.assertEqual(result.returncode, 0, result.stderr)
        results = json.loads(result.stdout.splitlines()[-1])
        for name, scores in results.items():
            with self.subTest(name=name):
                self.assertTrue(all(score['grading_error'] is None for score in scores), scores)
                self.assertEqual([score['correct'] for score in scores], [True, False])


if __name__ == '__main__':
    unittest.main()
