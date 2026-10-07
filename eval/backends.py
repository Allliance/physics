"""Shared no-tool generation and HLE-adapted judging for every dataset."""

import base64
import json
from pathlib import Path
import tempfile

from utils.fable_backend import (
    image_block, make_fable_client, parse_fable_response, resolve_fable_model,
)
from utils.codex_cli import CodexLLM, validate_codex_result

PROMPTS = Path(__file__).parent / 'prompts'
PREDICTION = (PROMPTS / 'prediction.txt').read_text()
JUDGE = (PROMPTS / 'judge.txt').read_text()
JUDGE_SYSTEM = (PROMPTS / 'judge_system.txt').read_text()
SCHEMA = json.loads((PROMPTS / 'judge_schema.json').read_text())
FINAL_ANSWER_SCHEMA = {
    'type': 'object', 'properties': {'final_answer': {'type': 'string'}},
    'required': ['final_answer'], 'additionalProperties': False,
}


def validate_judgment(content, schema=SCHEMA):
    if not isinstance(content, dict) or set(content) != set(schema['required']):
        raise ValueError('Judge response does not match the schema')
    if content['correct'] not in {'yes', 'no'} or (
            'strict' in schema['required'] and content['strict'] is not True):
        raise ValueError('Invalid correctness or strict flag')
    if type(content['confidence']) is not int or not 0 <= content['confidence'] <= 100:
        raise ValueError('Invalid confidence')
    for key in ('extracted_final_answer', 'reasoning'):
        if not isinstance(content[key], str) or not content[key].strip():
            raise ValueError(f'Empty/invalid {key}')


def validate_codex(result):
    validate_codex_result(result)


def image_path(question, directory):
    value = question.get('image')
    if not value:
        return None
    if not value.startswith('data:'):
        return Path(value)
    path = Path(directory) / 'question-image'
    path.write_bytes(base64.b64decode(value.split(',', 1)[1], validate=True))
    return path


def codex_client(args, judge=False, system_prompt=None):
    return CodexLLM(
        model=args.judge_model if judge else args.model,
        model_reasoning_effort=args.judge_reasoning_effort if judge else args.reasoning_effort,
        codex_bin=args.codex_bin, timeout=args.timeout,
        system_prompt=system_prompt or (JUDGE_SYSTEM if judge else PREDICTION),
        strict_no_tools=True, web_search='disabled', sandbox_mode='read-only', env_inherit='none',
        max_exec_retries=0, max_tool_retries=0,
    )


def make_predictor(args, api_model):
    if args.model == 'gemini-3.1-pro-preview':
        from utils.gemini_backend import generate

        def predict_gemini(question):
            return generate(question['prompt'] if 'prompt' in question else question['question'],
                            image=question.get('image'),
                            effort=args.reasoning_effort, max_output_tokens=args.max_output_tokens,
                            timeout=args.timeout,
                            system_prompt=question.get('system_prompt') or PREDICTION,
                            output_schema=FINAL_ANSWER_SCHEMA
                            if question.get('response_format') == 'json_final_answer' else None)

        return predict_gemini
    if args.model in {'gpt-oss-120b', 'kimi-k3', 'glm-5.3', 'deepseek-v4-pro',
                      'qwen3.8-27b'}:
        from utils.openai_compatible import generate

        def predict_openai_compatible(question):
            if question.get('image'):
                raise ValueError(f'{args.model} image input is not enabled in this evaluation')
            return generate(question['prompt'] if 'prompt' in question else question['question'],
                            system_prompt=question.get('system_prompt') or PREDICTION,
                            reasoning_effort=args.reasoning_effort,
                            max_output_tokens=args.max_output_tokens, timeout=args.timeout,
                            temperature=1.0 if args.model != 'gpt-oss-120b' else None,
                            top_p=(1.0 if args.model == 'deepseek-v4-pro' else 0.95)
                            if args.model != 'gpt-oss-120b' else None,
                            output_schema=FINAL_ANSWER_SCHEMA
                            if question.get('response_format') == 'json_final_answer' else None)

        return predict_openai_compatible
    client = make_fable_client(args.timeout) if args.model == 'claude-fable-5' else None
    codex_clients = {}

    def predict(question):
        # The caller passes only predictor_input(), never references or audit labels.
        prompt = question['prompt'] if 'prompt' in question else question['question']
        system_prompt = question.get('system_prompt') or PREDICTION
        with tempfile.TemporaryDirectory(prefix='physics-predict-') as directory:
            image = image_path(question, directory)
            if args.model == 'claude-fable-5':
                content = ([image_block(image)] if image else []) + [
                    {'type': 'text', 'text': prompt}]
                output_config = {'effort': args.reasoning_effort}
                if question.get('response_format') == 'json_final_answer':
                    output_config['format'] = {
                        'type': 'json_schema',
                        'schema': FINAL_ANSWER_SCHEMA,
                    }
                with client.messages.stream(
                    model=api_model, max_tokens=args.max_output_tokens, system=system_prompt,
                    messages=[{'role': 'user', 'content': content}],
                    thinking={'type': 'adaptive'}, output_config=output_config,
                ) as stream:
                    raw = stream.get_final_message().model_dump(mode='json')
                return {**parse_fable_response(raw, api_model), 'raw_response': raw}
            if system_prompt not in codex_clients:
                codex_clients[system_prompt] = codex_client(args, system_prompt=system_prompt)
            model_client = codex_clients[system_prompt]
            schema = None
            if question.get('response_format') == 'json_final_answer':
                schema = Path(directory) / 'answer-schema.json'
                schema.write_text(json.dumps(FINAL_ANSWER_SCHEMA))
            response = model_client.complete(prompt, image_paths=[image] if image else None,
                                             output_schema=schema)
        validate_codex(response)
        return {'response': response.text, 'usage': response.usage, 'actual_model': None,
                'requested_model': args.model, 'attempts': response.attempts,
                'tool_events': [], 'refused': False}
    return predict


def make_judge(args, *, judge_prompt=JUDGE, system_prompt=JUDGE_SYSTEM, schema=SCHEMA):
    fable = args.judge_model == 'claude-fable-5'
    api_model = resolve_fable_model(args.fable_model) if fable else None
    client = make_fable_client(args.timeout) if fable else codex_client(
        args, judge=True, system_prompt=system_prompt)

    def judge(question, prediction):
        if prediction.get('refused'):
            content = {'extracted_final_answer': 'None', 'reasoning': 'The evaluated model refused.',
                       'correct': 'no', 'confidence': 0, 'strict': True}
            if 'strict' not in schema['required']:
                content.pop('strict')
            return {'judgment': content, 'actual_model': None, 'judge_called': False}
        prompt = (judge_prompt(question, prediction) if callable(judge_prompt) else
                  judge_prompt.format(question=question['question'], response=prediction['response'],
                                      correct_answer=question['reference_answer']))
        with tempfile.TemporaryDirectory(prefix='physics-judge-') as directory:
            image = image_path(question, directory)
            if fable:
                content = ([image_block(image)] if image else []) + [{
                    'type': 'text', 'text': prompt + '\n\nOutput JSON schema:\n' + json.dumps(schema)}]
                with client.messages.stream(
                    model=api_model, max_tokens=args.judge_max_output_tokens, system=system_prompt,
                    messages=[{'role': 'user', 'content': content}],
                    thinking={'type': 'adaptive'}, output_config={'effort': args.judge_reasoning_effort},
                ) as stream:
                    raw = stream.get_final_message().model_dump(mode='json')
                parsed = parse_fable_response(raw, api_model)
                if parsed['refused']:
                    raise ValueError('Fable judge refused; judgment remains pending')
                judgment = json.loads(parsed['response'])
                validate_judgment(judgment, schema)
                return {'judgment': judgment, 'usage': parsed['usage'],
                        'raw_response': parsed['response'], 'raw_api_response': raw,
                        'requested_model': args.judge_model, 'actual_model': parsed['actual_model'],
                        'judge_called': True}
            schema_path = Path(directory) / 'schema.json'
            schema_path.write_text(json.dumps(schema))
            response = client.complete(prompt, output_schema=schema_path, image_paths=[image] if image else None)
        validate_codex(response)
        content = json.loads(response.text)
        validate_judgment(content, schema)
        return {'judgment': content, 'usage': response.usage, 'raw_response': response.text,
                'requested_model': args.judge_model, 'actual_model': None, 'judge_called': True}
    return judge
