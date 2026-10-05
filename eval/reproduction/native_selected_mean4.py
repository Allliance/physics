"""Four fresh no-tool attempts using native benchmark prompts and evaluators."""

import argparse
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import fcntl
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from eval.datasets import ROOT, load_dataset
from eval.storage import atomic_json, file_hash, fingerprint, require_checkpoint
from eval.reproduction.selected_mean4 import MODELS, DATASETS, ATTEMPTS
from eval.backends import validate_codex
from utils.fable_backend import make_fable_client, parse_fable_response, resolve_fable_model
from utils.codex_cli import CodexLLM
from utils.gemini_backend import generate as generate_gemini
from model_evals.gemini.run_suite import load_credentials
from model_evals.fable import evaluate_initial as native_base
from eval.pre_audit import native as released

LOCAL_MODELS = {
    'kimi': ('kimi-k3', 'gpt-5.6-sol'),
    'glm': ('glm-5.3', 'gpt-5.6-sol'),
    'deepseek': ('deepseek-v4-pro', 'gpt-5.6-sol'),
}


def predictor_input(row):
    return {k: row[k] for k in ('id', 'system_prompt', 'prompt')}


def generate_one(row, config, timeout):
    model = config['model']
    if model == 'claude-fable-5':
        return native_base.generate_one(row, config, timeout)
    if model == 'gemini-3.1-pro-preview':
        result = generate_gemini(row['prompt'], system_prompt=row['system_prompt'],
                                 effort='high', max_output_tokens=config['max_output_tokens'],
                                 timeout=timeout, output_schema=config.get('answer_schema'),
                                 use_tools=False, web_search=False)
    elif model in {'kimi-k3', 'glm-5.3', 'deepseek-v4-pro'}:
        from utils.openai_compatible import generate

        result = generate(row['prompt'], system_prompt=row['system_prompt'],
                          reasoning_effort='max', max_output_tokens=config['max_output_tokens'],
                          timeout=timeout, temperature=1.0,
                          top_p=1.0 if model == 'deepseek-v4-pro' else 0.95,
                          output_schema=config.get('answer_schema'))
    else:
        client = CodexLLM(model=model, model_reasoning_effort='high', timeout=timeout,
                          system_prompt=row['system_prompt'], strict_no_tools=True,
                          max_exec_retries=0, max_tool_retries=0)
        with tempfile.TemporaryDirectory(prefix='native-answer-schema-') as directory:
            schema = None
            if 'answer_schema' in config:
                schema = Path(directory) / 'schema.json'
                schema.write_text(json.dumps(config['answer_schema']))
            response = client.complete(row['prompt'], output_schema=schema)
        validate_codex(response)
        result = {'response': response.text, 'usage': response.usage, 'actual_model': None,
                  'requested_model': model, 'tool_events': [], 'refused': False}
    if 'answer_schema' in config:
        result.update(final_answer='', answer_format_error=None)
        if not result.get('refused'):
            try:
                result['final_answer'] = native_base.parse_final_answer(result['response'])
            except (ValueError, TypeError) as exc:
                result['answer_format_error'] = str(exc)
    return {**result, 'id': row['id'],
            'prompt_sha256': native_base.digest([row['system_prompt'], row['prompt']]),
            'created_at': datetime.now(timezone.utc).isoformat()}


def read(path):
    return json.loads(path.read_text())


def native_score(benchmark, row, prediction, timeout):
    response = prediction.get('final_answer', prediction['response'])
    result = native_base.grade_one(benchmark, row, response, timeout)
    return {**result, 'prediction_sha256': fingerprint(prediction)}


def auxiliary_judge(row, prediction, judge_model, timeout):
    prompt = released.auxiliary_prompt(row, prediction['response'], timeout)
    result = {'id': row['_eval_id'], 'prediction_sha256': fingerprint(prediction),
              'judge_model': judge_model, 'judge_reasoning_effort': 'high', 'tools': False}
    if prompt is None:
        return {**result, 'correct': False, 'judge_called': False,
                'reason': 'student answer extraction error'}
    if judge_model == 'claude-fable-5':
        api_model = resolve_fable_model(None)
        with make_fable_client(timeout) as client:
            with client.messages.stream(model=api_model, max_tokens=32768,
                    system=released.SYSTEM_PROMPT, messages=[{'role': 'user', 'content': prompt}],
                    thinking={'type': 'adaptive'}, output_config={'effort': 'high'}) as stream:
                raw = stream.get_final_message().model_dump(mode='json')
        parsed = parse_fable_response(raw, api_model)
        if parsed['refused']:
            raise ValueError('Auxiliary judge refused')
        result.update(report=parsed['response'], actual_model=parsed['actual_model'],
                      usage=parsed['usage'], raw_response=raw)
    else:
        client = CodexLLM(model=judge_model, model_reasoning_effort='high', timeout=timeout,
                          system_prompt=released.SYSTEM_PROMPT, strict_no_tools=True,
                          max_exec_retries=0, max_tool_retries=0)
        response = client.complete(prompt)
        validate_codex(response)
        result.update(report=response.text, actual_model=None, usage=response.usage)
    return {**result, 'correct': released.parse_verdict(result['report']), 'judge_called': True,
            'prompt_sha256': fingerprint(prompt)}


def summarize(ids, predictions, scores, auxiliary, benchmark):
    rows = []
    for qid in ids:
        native = scores.get(qid)
        final = (None if native is None else bool(native['correct'])
                 if benchmark != 'ugphysics' or native['correct'] else
                 bool(auxiliary[qid]['correct']) if qid in auxiliary else None)
        rows.append({'id': qid, 'correct': final,
                     'native_correct': None if native is None else bool(native['correct'])})
    complete = all(r['correct'] is not None for r in rows)
    return {'complete': complete, 'questions': len(ids), 'native_scored': len(scores),
            'generated': len(predictions),
            'auxiliary_judged': len(auxiliary), 'correct': sum(bool(r['correct']) for r in rows),
            'native_correct': sum(s['correct'] for s in scores.values()),
            'auxiliary_added': sum(a['correct'] for a in auxiliary.values()),
            'grading_errors': [qid for qid, s in scores.items() if s.get('grading_error')],
            'answer_format_errors': [qid for qid, p in predictions.items() if p.get('answer_format_error')],
            'accuracy': sum(bool(r['correct']) for r in rows) / len(ids) if complete else None,
            'per_question': rows}


def run_attempt(args):
    output = args.output / args.model / args.benchmark / f'attempt-{args.attempt}'
    output.mkdir(parents=True, exist_ok=True)
    with (output / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pre_audit, selection = load_dataset(args.benchmark, split='pre-audit')
        ids = [r['id'] for r in pre_audit]
        predictor, judge = LOCAL_MODELS.get(args.model, MODELS.get(args.model))
        # Reuse the existing native-source identity checks; this only prepares data.
        with tempfile.TemporaryDirectory(prefix='native-selected-') as temporary:
            preparation = argparse.Namespace(benchmark=args.benchmark, output=Path(temporary), max_output_tokens=32768)
            rows, native_config = native_base.prepare(preparation)
        native_rows = {r['id']: r['native'] for r in rows}
        config = {'version': 1, 'model': predictor, 'benchmark': args.benchmark,
                  'attempt': args.attempt, 'tools': False, 'fresh_generation': True,
                  'generation_protocol': 'Native benchmark prompt and original answer format.',
                  'reasoning_effort': 'max' if args.model in LOCAL_MODELS else 'high',
                  'api_model': resolve_fable_model(None) if predictor == 'claude-fable-5' else predictor,
                  'max_output_tokens': 65536 if args.model in {'gemini', *LOCAL_MODELS} else 32768,
                  'judge_model': judge if args.benchmark == 'ugphysics' else None,
                  'judge_reasoning_effort': 'high' if args.benchmark == 'ugphysics' else None,
                  'selection': selection, 'native_sample_sha256': fingerprint(rows),
                  'grader_sources': native_config['grader_sources'],
                  'evaluator_source': native_config['evaluator_source'],
                  'implementation_sha256': file_hash(Path(__file__)),
                  'backend_sha256': {str(p.relative_to(ROOT)): file_hash(p) for p in (
                      ROOT / 'utils/codex_cli/llm.py', ROOT / 'utils/gemini_backend.py',
                      ROOT / 'utils/openai_compatible.py',
                      ROOT / 'utils/fable_backend.py', Path(native_base.__file__))},
                  'grade_timeout': args.grade_timeout, 'judge_timeout': args.timeout,
                  'judge_max_output_tokens': 32768 if judge == 'claude-fable-5' else None,
                  'native_error_policy': 'Record native scoring exceptions/timeouts as non-passes, as in the original runners.'}
        if 'answer_schema' in native_config:
            config['answer_schema'] = native_config['answer_schema']
        if args.benchmark == 'ugphysics' and judge == 'claude-fable-5':
            config['judge_api_model'] = resolve_fable_model(None)
        if args.benchmark == 'ugphysics':
            config['auxiliary_prompt_sha256'] = file_hash(released.JUDGE_PROMPT_PATH)
        require_checkpoint(output / 'manifest.json', config)
        require_checkpoint(output / 'sample.json', rows)
        require_checkpoint(output / 'dataset.json', pre_audit)
        predictions = read(output / 'predictions.json') if (output / 'predictions.json').exists() else {}
        by_id = {r['id']: r for r in rows}
        if set(predictions) - set(ids):
            raise ValueError('Unexpected generation IDs')
        for qid, prediction in predictions.items():
            if (not prediction['response'].strip() or prediction.get('tool_events')
                    or prediction['prompt_sha256'] != native_base.digest([by_id[qid]['system_prompt'], by_id[qid]['prompt']])):
                raise ValueError('Invalid generation checkpoint')
        scores = read(output / 'scores.json') if (output / 'scores.json').exists() else {}
        auxiliary = read(output / 'auxiliary.json') if (output / 'auxiliary.json').exists() else {}
        for records in (scores, auxiliary):
            if set(records) - set(ids):
                raise ValueError('Unexpected checkpoint IDs')
            for qid, record in records.items():
                if qid not in predictions or record['prediction_sha256'] != fingerprint(predictions[qid]):
                    raise ValueError('Prediction changed after scoring')
        def save_report():
            value = summarize(ids, predictions, scores, auxiliary, args.benchmark)
            atomic_json(output / 'summary.json', value)
            return value
        for stage in ('generate', 'score', 'auxiliary'):
            if args.stage == 'prepare' or (args.stage != 'all' and args.stage != stage):
                continue
            if stage == 'generate':
                pending = [qid for qid in ids if qid not in predictions]
                pool = ThreadPoolExecutor(max_workers=args.workers)
                function = generate_one
                arguments = lambda qid: (predictor_input(by_id[qid]), config, args.timeout)
                checkpoint, filename = predictions, 'predictions.json'
            elif stage == 'score':
                pending = [qid for qid in ids if qid in predictions and qid not in scores]
                pool = ProcessPoolExecutor(max_workers=args.score_workers, mp_context=multiprocessing.get_context('fork'))
                function = native_score
                arguments = lambda qid: (args.benchmark, native_rows[qid], predictions[qid], args.grade_timeout)
                checkpoint, filename = scores, 'scores.json'
            elif args.benchmark == 'ugphysics':
                pending = [qid for qid in ids if qid in scores and not scores[qid]['correct'] and qid not in auxiliary]
                pool = ThreadPoolExecutor(max_workers=args.judge_workers)
                function = auxiliary_judge
                arguments = lambda qid: (native_rows[qid], predictions[qid], judge, args.timeout)
                checkpoint, filename = auxiliary, 'auxiliary.json'
            else:
                continue
            if args.limit:
                pending = pending[:args.limit]
            with pool:
                futures = {pool.submit(function, *arguments(qid)): qid for qid in pending}
                for future in as_completed(futures):
                    qid = futures[future]
                    try:
                        checkpoint[qid] = future.result()
                        atomic_json(output / filename, checkpoint)
                    except Exception as exc:
                        with (output / 'errors.jsonl').open('a') as handle:
                            handle.write(json.dumps({'id': qid, 'stage': stage,
                                'error': f'{type(exc).__name__}: {exc}', 'time': datetime.now(timezone.utc).isoformat()}) + '\n')
                        print(f'{stage} FAILED {qid}: {exc}', flush=True)
                    save_report()
                    print(f'{stage} {len(checkpoint)}/100 {qid}', flush=True)
        result = save_report()
        return 0 if result['complete'] or args.stage == 'prepare' else 2


def suite_report(output):
    results = {}
    for model in MODELS:
        for benchmark in DATASETS:
            attempts = []
            for attempt in range(1, ATTEMPTS + 1):
                p = output / model / benchmark / f'attempt-{attempt}' / 'summary.json'
                attempts.append(read(p) if p.exists() else None)
            complete = all(a and a['complete'] for a in attempts)
            available = [a for a in attempts if a]
            results[f'{model}/{benchmark}'] = {
                'complete': complete, 'questions': 100, 'attempts_per_question': 4,
                'generated': sum(a['generated'] for a in available),
                'native_scored': sum(a['native_scored'] for a in available),
                'auxiliary_judged': sum(a['auxiliary_judged'] for a in available),
                'auxiliary_added': sum(a['auxiliary_added'] for a in available),
                'native_correct': sum(a['native_correct'] for a in available),
                'correct': sum(a['correct'] for a in available) if complete else None,
                'mean_at_4_percent': sum(a['correct'] for a in available) / 4 if complete else None,
                'grading_errors': sum(len(a['grading_errors']) for a in available),
                'answer_format_errors': sum(len(a['answer_format_errors']) for a in available),
                'per_attempt': attempts}
    value = {'complete': all(r['complete'] for r in results.values()),
             'updated_at': datetime.now(timezone.utc).isoformat(), 'fresh_generation': True,
             'metric': 'Native-evaluator mean@4 on all 100 selected questions.',
             'generation_protocol': 'Native benchmark prompts and output formats; four independent no-tool attempts.',
             'results': results}
    atomic_json(output / 'summary.json', value)
    lines = ['# Native-prompt mean@4 without tools', '',
             'All 100 selected questions per benchmark; original references; four fresh independent answers per question. '
             'Generation and scoring use each benchmark\'s native prompt and evaluator.', '',
             '| Model | Dataset | Generated | Native scored | Auxiliary judged | Mean@4 |',
             '|---|---|---:|---:|---:|---:|']
    for name, r in results.items():
        score = f"{r['mean_at_4_percent']:.2f}%" if r['complete'] else 'Pending'
        lines.append(f"| {name.split('/')[0]} | {name.split('/')[1]} | {r['generated']}/400 | {r['native_scored']}/400 | {r['auxiliary_judged']} | {score} |")
    lines += ['', 'PHYBench: original final-answer JSON schema, EED = 100. '
              'PRISM: released equation-format instructions; all final-answer DAG formulas must match. '
              'UGPhysics: released rule grader and auxiliary prompt, Fable High judging Gemini/Sol, '
              'Sol High judging Fable; judges use no tools.', '',
              'Native scorer errors count as non-passes and are listed separately. '
              'Failed auxiliary model requests remain pending.', '', f"Updated: {value['updated_at']}", '']
    (output / 'progress.md').write_text('\n'.join(lines))
    return value


def supervise(args):
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / '.suite.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.stage == 'summary':
            return 0 if suite_report(args.output)['complete'] else 2
        if args.stage in {'all', 'generate'}:
            load_credentials()
        logs = args.output / 'logs'
        logs.mkdir(exist_ok=True)
        commands = {}
        for attempt in range(1, 5):
            for model in MODELS:
                for benchmark in DATASETS:
                    name = f'{model}-{benchmark}-{attempt}'
                    cmd = [sys.executable, '-u', '-m', 'eval.reproduction.native_selected_mean4',
                           '--output', str(args.output), '--model', model,
                           '--benchmark', benchmark, '--attempt', str(attempt), '--stage', args.stage,
                           '--workers', str(args.workers),
                           '--score-workers', str(args.score_workers), '--judge-workers', str(args.judge_workers),
                           '--grade-timeout', str(args.grade_timeout), '--timeout', str(args.timeout)]
                    if args.limit:
                        cmd += ['--limit', str(args.limit)]
                    commands[name] = cmd
        require_checkpoint(args.output / 'suite-manifest.json', {
            'version': 1, 'implementation_sha256': file_hash(Path(__file__)),
            'models_and_judges': {k: list(v) for k, v in MODELS.items()},
            'datasets': list(DATASETS), 'attempts': ATTEMPTS, 'tools': False,
            'generation_protocol': 'Fresh native benchmark prompts and answers.'})
        atomic_json(args.output / 'commands.json', commands)
        atomic_json(args.output / 'supervisor.json', {'pid': os.getpid(), 'state': 'running'})
        def execute(name, cmd):
            for invocation in range(args.retries + 1):
                with (logs / f'{name}.log').open('a') as log:
                    process = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
                    atomic_json(logs / f'{name}.pid.json', {'pid': process.pid, 'command': cmd})
                    code = process.wait()
                if code == 0 or args.limit:
                    break
                if invocation < args.retries:
                    time.sleep(20)
            print(name, 'exit', code, flush=True)
            return code
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = [pool.submit(execute, name, cmd) for name, cmd in commands.items()]
            while not all(f.done() for f in futures):
                report = suite_report(args.output)
                print('Generated:', sum(r['generated'] for r in report['results'].values()),
                      'Native scored:', sum(r['native_scored'] for r in report['results'].values()), flush=True)
                time.sleep(20)
            for future in futures:
                future.result()
        complete = suite_report(args.output)['complete']
        atomic_json(args.output / 'supervisor.json', {'pid': os.getpid(), 'state': 'complete' if complete else 'pending'})
        return 0 if complete or args.stage == 'prepare' else 2


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--model', choices=[*MODELS, *LOCAL_MODELS])
    p.add_argument('--benchmark', choices=list(DATASETS))
    p.add_argument('--attempt', type=int, choices=range(1,5))
    p.add_argument('--stage', choices=['prepare', 'generate', 'score', 'auxiliary', 'all', 'summary'], default='all')
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--score-workers', type=int, default=4)
    p.add_argument('--judge-workers', type=int, default=8)
    p.add_argument('--jobs', type=int, default=9)
    p.add_argument('--grade-timeout', type=float, default=180)
    p.add_argument('--timeout', type=float, default=1800)
    p.add_argument('--retries', type=int, default=3)
    p.add_argument('--limit', type=int)
    args = p.parse_args()
    args.output = args.output.resolve()
    if any((args.model, args.benchmark, args.attempt)) and not all((args.model, args.benchmark, args.attempt)):
        p.error('Supply model, benchmark, and attempt together')
    if min(args.workers, args.score_workers, args.judge_workers, args.jobs, args.grade_timeout, args.timeout) <= 0 or args.retries < 0 or (args.limit is not None and args.limit <= 0):
        p.error('Limits must be positive and retries nonnegative')
    return run_attempt(args) if args.model else supervise(args)


if __name__ == '__main__':
    raise SystemExit(main())
