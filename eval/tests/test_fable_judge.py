import json
import unittest
from unittest.mock import MagicMock, patch

from eval.backends import make_judge
from eval.post_audit import parser


class FableJudgeTests(unittest.TestCase):
    def test_validated_api_judgments_and_pending_failures(self):
        args = parser().parse_args(['--dataset', 'phybench', '--output', '/tmp/unused',
                                    '--model', 'gpt-5.6-sol', '--judge-model', 'claude-fable-5'])
        judgment = {'extracted_final_answer': '2', 'reasoning': 'Equivalent.', 'correct': 'yes',
                    'confidence': 100, 'strict': True}
        valid = {'model': 'claude-fable-5', 'stop_reason': 'end_turn', 'usage': {},
                 'content': [{'type': 'text', 'text': json.dumps(judgment)}]}
        client = MagicMock()
        message = client.messages.stream.return_value.__enter__.return_value.get_final_message.return_value
        with patch('eval.backends.make_fable_client', return_value=client), patch(
                'eval.backends.resolve_fable_model', return_value='fable-alias'):
            judge = make_judge(args)
            message.model_dump.return_value = valid
            result = judge({'question': 'Q', 'reference_answer': '2'}, {'response': '2'})
            self.assertEqual(result['actual_model'], 'claude-fable-5')
            self.assertEqual(result['judgment'], judgment)
            kwargs = client.messages.stream.call_args.kwargs
            self.assertEqual(kwargs['model'], 'fable-alias')
            self.assertEqual(kwargs['thinking'], {'type': 'adaptive'})
            self.assertEqual(kwargs['output_config'], {'effort': 'high'})
            self.assertEqual(kwargs['max_tokens'], 8192)
            for change in ({'model': 'wrong'}, {'stop_reason': 'refusal'},
                           {'content': [{'type': 'text', 'text': '{}'}]}):
                message.model_dump.return_value = {**valid, **change}
                with self.assertRaises(ValueError):
                    judge({'question': 'Q', 'reference_answer': '2'}, {'response': '2'})
