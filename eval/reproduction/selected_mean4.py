"""Four independent no-tool runs on each frozen selected audit dataset."""

import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from eval.backends import validate_judgment
from eval.datasets import ROOT, load_dataset
from eval.storage import atomic_json, file_hash, fingerprint, require_checkpoint

MODELS = {'gemini': ('gemini-3.1-pro-preview', 'claude-fable-5'),
          'sol': ('gpt-5.6-sol', 'claude-fable-5'),
          'fable': ('claude-fable-5', 'gpt-5.6-sol')}
DATASETS = ('phybench', 'ugphysics', 'prism')
ATTEMPTS = 4


def commands(output, workers):
    jobs = {}
    for attempt in range(1, ATTEMPTS + 1):
        for model, (predictor, judge) in MODELS.items():
            for dataset in DATASETS:
                name = f'{model}/{dataset}/attempt-{attempt}'
                jobs[name] = [sys.executable, '-u', '-m', 'eval', 'post-audit',
                              '--dataset', dataset, '--data',
                              str(ROOT / 'eval/data/pre_audit' / f'{dataset}.jsonl'),
                              '--output', str(output / name),
                              '--model', predictor, '--judge-model', judge,
                              '--reasoning-effort', 'high', '--judge-reasoning-effort', 'high',
                              '--mode', 'merged', '--max-output-tokens',
                              '65536' if model == 'gemini' else '32768',
                              '--judge-max-output-tokens', '32768',
                              '--timeout', '1800', '--workers', str(workers)]
    return jobs


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def aggregate(rows, attempts):
    """Missing attempts/grades keep the entire mean pending, with a fixed denominator."""
    if len(attempts) != ATTEMPTS:
        raise ValueError('Exactly four attempt checkpoints are required')
    ids = {row['id'] for row in rows}
    if not ids or len(ids) != len(rows):
        raise ValueError('Question IDs must be nonempty and unique')
    results = []
    predictions_count = judgments_count = 0
    for predictions, judgments in attempts:
        if set(predictions) - ids or set(judgments) - set(predictions):
            raise ValueError('Unexpected prediction/judgment IDs')
        for qid, prediction in predictions.items():
            if not prediction.get('response', '').strip() or prediction.get('tool_events'):
                raise ValueError(f'Invalid no-tool prediction: {qid}')
        for qid, result in judgments.items():
            validate_judgment(result['judgment'])
            if result['prediction_sha256'] != fingerprint(predictions[qid]):
                raise ValueError(f'Prediction changed after judging: {qid}')
        predictions_count += len(predictions)
        judgments_count += len(judgments)
    for row in rows:
        grades = [int(j[row['id']]['judgment']['correct'] == 'yes')
                  if row['id'] in j else None for _, j in attempts]
        results.append({'id': row['id'], 'grades': grades,
                        'mean_at_4': sum(grades) / ATTEMPTS if None not in grades else None})
    complete = judgments_count == len(rows) * ATTEMPTS
    correct = sum(g or 0 for row in results for g in row['grades'])
    return {'complete': complete, 'questions': len(rows), 'attempts_per_question': ATTEMPTS,
            'expected_answers': len(rows) * ATTEMPTS, 'predictions': predictions_count,
            'judgments': judgments_count, 'correct_answers': correct,
            'mean_at_4': correct / (len(rows) * ATTEMPTS) if complete else None,
            'mean_at_4_percent': 100 * correct / (len(rows) * ATTEMPTS) if complete else None,
            'per_question': results}


def report(output):
    results = {}
    for model, (predictor, judge) in MODELS.items():
        for dataset in DATASETS:
            name = f'{model}/{dataset}'
            prepared = output / name / 'attempt-1/dataset.json'
            if not prepared.exists():
                results[name] = {'complete': False, 'predictions': 0, 'judgments': 0}
                continue
            rows = read_json(prepared, [])
            attempts = []
            for attempt in range(1, ATTEMPTS + 1):
                directory = output / name / f'attempt-{attempt}'
                saved = read_json(directory / 'dataset.json', rows)
                if saved != rows:
                    raise ValueError(f'Dataset changed between attempts: {name}')
                attempts.append((read_json(directory / 'predictions.json', {}),
                                 read_json(directory / 'judgments.json', {})))
            results[name] = {**aggregate(rows, attempts), 'model': predictor, 'judge_model': judge}
    value = {'updated_at': datetime.now(timezone.utc).isoformat(),
             'complete': all(r['complete'] for r in results.values()),
             'split': 'pre-audit', 'tools': False, 'reasoning_effort': 'high',
             'judge_reasoning_effort': 'high', 'results': results}
    atomic_json(output / 'summary.json', value)
    lines = ['# Selected-data mean@4 (no tools)', '',
             'Four fresh independent answers per question, merged binary judging. '
             'All 100 selected questions and original references are retained per dataset.', '',
             '| Model | Dataset | Answers | Judgments | Mean@4 |',
             '|---|---|---:|---:|---:|']
    for name, result in results.items():
        model, dataset = name.split('/')
        score = f"{result['mean_at_4_percent']:.2f}%" if result['complete'] else 'Pending'
        lines.append(f"| {model} | {dataset} | {result['predictions']}/400 | "
                     f"{result['judgments']}/400 | {score} |")
    lines.extend(['', 'Gemini and Sol use Fable 5 High as judge; Fable uses GPT-5.6-Sol High.',
                  '', f"Updated: {value['updated_at']}", ''])
    temporary = output / 'progress.md.tmp'
    temporary.write_text('\n'.join(lines))
    temporary.replace(output / 'progress.md')
    return value


def execute(name, command, args):
    log_path = args.output / 'logs' / (name.replace('/', '-') + '.log')
    # A previously launched smoke may still hold this attempt's lock. Wait for
    # it while other jobs advance, then let the evaluator resume its checkpoint.
    attempt_lock = args.output / name / '.lock'
    if attempt_lock.exists():
        with attempt_lock.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            fcntl.flock(lock, fcntl.LOCK_UN)
    command = command + ['--stage', args.stage]
    if args.max_pending:
        command += ['--max-pending', str(args.max_pending)]
    for invocation in range(args.retries + 1):
        with log_path.open('a') as log:
            log.write(f'\nInvocation {invocation + 1}: {json.dumps(command)}\n')
            log.flush()
            process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            atomic_json(log_path.with_suffix('.pid.json'), {'pid': process.pid, 'command': command})
            code = process.wait()
        if code == 0 or args.max_pending or args.stage == 'prepare':
            break
        if invocation < args.retries:
            time.sleep(30)
    print(f'{name}: exit {code}', flush=True)
    return code


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--jobs', type=int, default=9)
    p.add_argument('--retries', type=int, default=3)
    p.add_argument('--max-pending', type=int)
    p.add_argument('--stage', choices=['prepare', 'all', 'summary'], default='all')
    args = p.parse_args(argv)
    if min(args.workers, args.jobs) <= 0 or args.retries < 0 or (
            args.max_pending is not None and args.max_pending <= 0):
        p.error('Worker/job/pending limits must be positive and retries nonnegative')
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / '.suite.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.stage == 'summary':
            return 0 if report(args.output)['complete'] else 2
        selections = {d: load_dataset(d, split='pre-audit')[1] for d in DATASETS}
        require_checkpoint(args.output / 'suite-manifest.json', {
            'version': 1, 'models_and_judges': {k: list(v) for k, v in MODELS.items()}, 'attempts': ATTEMPTS,
            'split': 'pre-audit', 'tools': False, 'fresh_generation': True,
            'selections': selections, 'supervisor_sha256': file_hash(Path(__file__))})
        jobs = commands(args.output, args.workers)
        atomic_json(args.output / 'commands.json', jobs)
        (args.output / 'logs').mkdir(exist_ok=True)
        if args.stage == 'all':
            from model_evals.gemini.run_suite import load_credentials
            load_credentials()
        atomic_json(args.output / 'supervisor.json', {'pid': os.getpid(), 'state': 'running'})
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            pending = {pool.submit(execute, name, cmd, args): name for name, cmd in jobs.items()}
            while pending:
                done, _ = wait(pending, timeout=30, return_when=FIRST_COMPLETED)
                for future in done:
                    future.result()
                    del pending[future]
                progress = report(args.output)
                print(f"Progress: {sum(r['predictions'] for r in progress['results'].values())} answers, "
                      f"{sum(r['judgments'] for r in progress['results'].values())} judgments", flush=True)
        progress = report(args.output)
        atomic_json(args.output / 'supervisor.json', {
            'pid': os.getpid(), 'state': 'complete' if progress['complete'] else 'pending'})
        return 0 if progress['complete'] or args.stage == 'prepare' else 2


if __name__ == '__main__':
    raise SystemExit(main())
