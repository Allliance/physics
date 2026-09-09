"""Network-free checks of Gemini evaluation protocol and failure semantics."""

import base64
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from utils.gemini_backend import (
    MODEL, GeminiAPIError, GeminiLimitError, backend_metadata, build_request,
    generate, parse_response,
)


def response(parts=None, stop='STOP'):
    return {'modelVersion': MODEL, 'usageMetadata': {'thoughtsTokenCount': 23},
            'candidates': [{'finishReason': stop,
                            'content': {'parts': parts or [{'text': 'answer'}]}}]}


class GeminiBackendTests(unittest.TestCase):
    def test_max_is_recorded_as_high_without_claiming_distinct_effort(self):
        self.assertEqual(build_request('q', effort='max')['generationConfig']['thinkingConfig'],
                         {'thinkingLevel': 'high'})
        result = parse_response(response(), effort='max')
        self.assertEqual(result['requested_reasoning_effort'], 'max')
        self.assertEqual(result['effective_thinking_level'], 'high')
        self.assertEqual(backend_metadata('max')['effective_thinking_level'], 'high')

    def test_tool_modes_and_output_budget_validation(self):
        self.assertNotIn('tools', build_request('q'))
        self.assertEqual(build_request('q', use_tools=True, web_search='live')['tools'],
                         [{'codeExecution': {}}, {'googleSearch': {}}])
        for kwargs in ({'web_search': True}, {'max_output_tokens': 65537},
                       {'effort': 'xhigh'}, {'web_search': 'cached'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_request('q', **kwargs)

    def test_image_data_url_and_extensionless_file(self):
        data = b'\x89PNG\r\n\x1a\nexample'
        url = 'data:image/png;base64,' + base64.b64encode(data).decode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'image'
            path.write_bytes(data)
            self.assertEqual(build_request('q', url), build_request('q', path))

    def test_system_and_json_schema_do_not_change_question(self):
        schema = {'type': 'object', 'properties': {'final_answer': {'type': 'string'}}}
        body = build_request('q', system_prompt='s', output_schema=schema)
        self.assertEqual(body['contents'][0]['parts'], [{'text': 'q'}])
        self.assertEqual(body['systemInstruction']['parts'], [{'text': 's'}])
        self.assertEqual(body['generationConfig']['responseJsonSchema'], schema)

    def test_thoughts_excluded_and_tool_events_preserved(self):
        raw = response([{'thought': True, 'text': 'private thought summary'},
                        {'executableCode': {'language': 'PYTHON', 'code': 'print(2)'}},
                        {'codeExecutionResult': {'outcome': 'OUTCOME_OK', 'output': '2'}},
                        {'text': 'answer'}])
        result = parse_response(raw, use_tools=True)
        self.assertEqual(result['response'], 'answer')
        self.assertEqual(len(result['tool_events']), 2)
        with self.assertRaises(GeminiAPIError):
            parse_response(raw)

    def test_refusal_is_a_scored_response(self):
        result = parse_response({'promptFeedback': {'blockReason': 'SAFETY'}})
        self.assertTrue(result['refused'])
        self.assertIn('refused', result['response'])

    def test_generation_limit_preserves_partial_attempt(self):
        with self.assertRaises(GeminiLimitError) as caught:
            parse_response(response(stop='MAX_TOKENS'))
        self.assertEqual(caught.exception.result['response'], 'answer')
        self.assertEqual(caught.exception.result['usage']['thoughtsTokenCount'], 23)

    def test_empty_incomplete_and_wrong_model_fail(self):
        wrong = response()
        wrong['modelVersion'] = 'gemini-3-flash-preview'
        for raw in ({}, response([{'thought': True, 'text': 'thinking'}]), wrong):
            with self.subTest(raw=raw), self.assertRaises(GeminiAPIError):
                parse_response(raw)
        wrong['candidates'][0]['finishReason'] = 'MAX_TOKENS'
        with self.assertRaises(GeminiAPIError):
            parse_response(wrong)

    def test_credentials_missing_and_http_errors_do_not_leak(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(GeminiAPIError):
            generate('q')
        error = urllib.error.HTTPError('secret-url', 429, 'secret-key', {}, None)
        with patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaises(GeminiAPIError) as caught:
                generate('q', api_key='secret-key')
        self.assertEqual(str(caught.exception), 'Gemini API HTTP 429')


if __name__ == '__main__':
    unittest.main()
