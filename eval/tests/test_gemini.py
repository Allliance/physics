import unittest
from unittest.mock import patch

from eval.backends import make_predictor
from eval.post_audit import parser


class GeminiTests(unittest.TestCase):
    def test_predictor_uses_gemini_without_codex_or_reference(self):
        args = parser().parse_args(['--dataset', 'phybench', '--output', '/unused',
                                   '--model', 'gemini-3.1-pro-preview',
                                   '--judge-model', 'claude-fable-5'])
        with patch('utils.gemini_backend.generate', return_value={'response': '2'}) as generate, patch(
                'eval.backends.codex_client') as codex:
            result = make_predictor(args, None)({'id': '1', 'question': 'QUESTION'})
        self.assertEqual(result['response'], '2')
        self.assertEqual(generate.call_args.args, ('QUESTION',))
        self.assertEqual(generate.call_args.kwargs['effort'], 'high')
        codex.assert_not_called()

if __name__ == '__main__':
    unittest.main()
