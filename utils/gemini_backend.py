"""Gemini 3.1 Pro evaluation transport using Google's generateContent API.

Set GOOGLE_API_KEY or GEMINI_API_KEY. Requests are independent, with no tool
access unless explicitly enabled. ``max`` means Google's highest supported
thinking level (``high``), and both the request and effective level are saved.
Native code execution/search are server managed; they are not a local shell.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
import urllib.error
import urllib.request

MODEL = 'gemini-3.1-pro-preview'
BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'
MAX_OUTPUT_TOKENS = 65536


class GeminiAPIError(RuntimeError):
    """A failed request; callers may retry without counting a model attempt."""


class GeminiLimitError(RuntimeError):
    """The model exhausted an inference limit; preserve as a scored attempt."""

    def __init__(self, message, result):
        super().__init__(message)
        self.result = result


def effective_thinking_level(effort):
    if effort not in {'low', 'medium', 'high', 'max'}:
        raise ValueError(f'Unsupported Gemini reasoning effort: {effort}')
    return 'high' if effort == 'max' else effort


def backend_metadata(effort='high'):
    """Nonsecret settings for reproducible manifests and cache validation."""
    return {'provider': 'google', 'api': 'generateContent', 'model': MODEL,
            'base_url': BASE_URL, 'requested_reasoning_effort': effort,
            'effective_thinking_level': effective_thinking_level(effort),
            'temperature': 1.0, 'candidate_count': 1,
            'tool_backend': 'google_native_code_execution_and_search',
            'max_supported_output_tokens': MAX_OUTPUT_TOKENS}


def _image_part(image):
    if isinstance(image, str) and image.startswith('data:'):
        header, encoded = image.split(',', 1)
        mime_type = header[5:].split(';', 1)[0]
        if not header.endswith(';base64'):
            raise ValueError('Gemini image data URLs must use base64')
        data = base64.b64decode(encoded, validate=True)
    else:
        path = Path(image)
        data = path.read_bytes()
        mime_type = mimetypes.guess_type(str(path))[0]
        # Corrected evaluation temporary image paths do not carry extensions.
        if not mime_type:
            if data.startswith(b'\x89PNG\r\n\x1a\n'):
                mime_type = 'image/png'
            elif data.startswith(b'\xff\xd8\xff'):
                mime_type = 'image/jpeg'
            elif data.startswith((b'GIF87a', b'GIF89a')):
                mime_type = 'image/gif'
            elif data.startswith(b'RIFF') and data[8:12] == b'WEBP':
                mime_type = 'image/webp'
    if not mime_type or not mime_type.startswith('image/'):
        raise ValueError('Unable to determine Gemini image MIME type')
    return {'inlineData': {'mimeType': mime_type,
                           'data': base64.b64encode(data).decode('ascii')}}


def build_request(prompt, image=None, *, effort='high', max_output_tokens=MAX_OUTPUT_TOKENS,
                  system_prompt=None, output_schema=None, use_tools=False, web_search=False):
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('Gemini prompt must be nonempty text')
    if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= MAX_OUTPUT_TOKENS:
        raise ValueError(f'Gemini max_output_tokens must be between 1 and {MAX_OUTPUT_TOKENS}')
    search = web_search is True or web_search == 'live'
    if web_search not in (False, True, 'disabled', 'live', None):
        raise ValueError('Gemini web_search must be disabled or live')
    if search and not use_tools:
        raise ValueError('Gemini web search requires use_tools=True')
    parts = ([_image_part(image)] if image is not None else []) + [{'text': prompt}]
    body = {'contents': [{'role': 'user', 'parts': parts}], 'generationConfig': {
        'thinkingConfig': {'thinkingLevel': effective_thinking_level(effort)},
        'maxOutputTokens': max_output_tokens,
        'temperature': 1.0,
        'candidateCount': 1,
    }}
    if system_prompt:
        body['systemInstruction'] = {'parts': [{'text': system_prompt}]}
    if output_schema is not None:
        body['generationConfig'].update(responseMimeType='application/json',
                                        responseJsonSchema=output_schema)
    if use_tools:
        body['tools'] = [{'codeExecution': {}}]
        if search:
            body['tools'].append({'googleSearch': {}})
    return body


def parse_response(raw, *, effort='high', use_tools=False, web_search=False):
    candidates = raw.get('candidates') or []
    if len(candidates) > 1:
        raise GeminiAPIError('Gemini returned multiple candidates for a single attempt')
    candidate = candidates[0] if candidates else {}
    parts = candidate.get('content', {}).get('parts', [])
    tool_events = []
    for part in parts:
        for kind in ('executableCode', 'codeExecutionResult', 'functionCall', 'functionResponse'):
            if kind in part:
                tool_events.append({'type': kind, **part[kind]})
    grounding = candidate.get('groundingMetadata')
    if grounding:
        tool_events.append({'type': 'groundingMetadata', **grounding})
    if tool_events and not use_tools:
        raise GeminiAPIError('Gemini returned tool events during a no-tools request')
    if any(e['type'] == 'functionCall' for e in tool_events):
        raise GeminiAPIError('Gemini requested an undeclared external function')
    stop = candidate.get('finishReason')
    blocked = raw.get('promptFeedback', {}).get('blockReason')
    refused = bool(blocked) or stop in {
        'SAFETY', 'RECITATION', 'BLOCKLIST', 'PROHIBITED_CONTENT', 'SPII', 'IMAGE_SAFETY'}
    response = ''.join(p.get('text', '') for p in parts if not p.get('thought'))
    if refused and not response.strip():
        response = '[The evaluated model refused to answer.]'
    result = {'response': response, 'usage': raw.get('usageMetadata'),
              'requested_model': MODEL, 'actual_model': raw.get('modelVersion'),
              'requested_reasoning_effort': effort,
              'effective_thinking_level': effective_thinking_level(effort),
              'raw_response': raw, 'tool_events': tool_events, 'refused': refused,
              'stop_reason': stop or blocked, 'attempts': 1,
              'tool_backend': 'google_native' if use_tools else None,
              'web_search': 'live' if web_search is True or web_search == 'live' else 'disabled',
              'tool_turn_limit': 'server_managed' if use_tools else None}
    actual_model = result['actual_model']
    if actual_model and not actual_model.startswith(MODEL):
        raise GeminiAPIError(f'Unexpected Gemini model version: {actual_model}')
    if stop in {'MAX_TOKENS', 'TOO_MANY_TOOL_CALLS'}:
        raise GeminiLimitError(f'Gemini inference limit: {stop}', result)
    if not refused and (stop != 'STOP' or not response.strip()):
        raise GeminiAPIError(f'Gemini response did not complete: {stop or "missing candidate"}')
    return result


def generate(prompt, image=None, *, effort='high', max_output_tokens=MAX_OUTPUT_TOKENS,
             timeout=1200, system_prompt=None, output_schema=None, use_tools=False,
             web_search=False, api_key=None):
    """Generate one answer, preserving refusal and inference-limit semantics.

    API/transport failures raise GeminiAPIError. Inference limits raise
    GeminiLimitError with the partial normalized response in ``result``.
    Retries belong to the benchmark runner so attempts remain auditable.
    """
    body = build_request(prompt, image, effort=effort, max_output_tokens=max_output_tokens,
                         system_prompt=system_prompt, output_schema=output_schema,
                         use_tools=use_tools, web_search=web_search)
    key = api_key or os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY')
    if not key:
        raise GeminiAPIError('Set GOOGLE_API_KEY or GEMINI_API_KEY to evaluate Gemini')
    request = urllib.request.Request(
        f'{BASE_URL}/models/{MODEL}:generateContent', data=json.dumps(body).encode(),
        headers={'x-goog-api-key': key, 'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not echo provider messages, request headers, URLs, or credentials.
        raise GeminiAPIError(f'Gemini API HTTP {exc.code}') from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise GeminiAPIError(f'Gemini transport failure: {type(exc).__name__}') from None
    return parse_response(raw, effort=effort, use_tools=use_tools, web_search=web_search)
