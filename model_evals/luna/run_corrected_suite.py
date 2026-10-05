#!/usr/bin/env python3
"""Run the corrected GPT-5.6-Luna High suite in a fixed benchmark order."""

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval.storage import atomic_json, file_hash, fingerprint, require_checkpoint

MODEL = 'gpt-5.6-luna'
JUDGE = 'claude-fable-5'
ORDER = ('phybench', 'prism', 'ugphysics', 'hle', 'cmt', 'critpt')
SOURCE = ROOT / 'model_evals/gemini/runs/gemini31-20260908/repeated'
GEMINI_RUN = ROOT / 'model_evals/gemini/runs/gemini31-20260908'
REJUDGE = ROOT / 'model_evals/gemini/runs/sol-rejudge-corrected-20260914/comparison.json'
TAG = 'luna-high-corrected-20260914'


def commands(output: Path, workers: int) -> dict:
    common = ['--model', MODEL, '--judge-model', JUDGE, '--reasoning-effort', 'high',
              '--judge-reasoning-effort', 'high']
    jobs = {}
    for benchmark in ORDER[:3]:
        destination = output / benchmark / 'frozen-gemini-corrected'
        jobs[benchmark] = [sys.executable, '-u', '-m', 'eval',
            '--dataset', f'{benchmark}-frozen-gemini-corrected',
            '--data', str(GEMINI_RUN / benchmark / 'corrected/dataset.json'),
            '--split', 'corrected', '--output', str(destination), *common, '--mode', 'merged',
            '--max-output-tokens', '32768', '--judge-max-output-tokens', '32768',
            '--timeout', '1800', '--workers', str(workers)]
    hle_output = ROOT / f'benchmarks/hle/artifacts/{TAG}/hle-corrected-no-tools.json'
    jobs['hle'] = [sys.executable, '-u', str(ROOT / 'benchmarks/hle/evaluate.py'),
        '--dataset', str(SOURCE / 'hle-corrected.json'), '--category', 'Physics',
        '--no-include-images', *common, '--rounds', '4', '--aggregation', 'mean',
        '--num-workers', str(workers), '--round-workers', '4', '--timeout', '1800',
        '--limit-policy', 'incorrect', '--no-use-tools', '--web-search', 'disabled',
        '--output', str(hle_output)]
    cmt_output = ROOT / f'analysis/CMT-Benchmark/artifacts/{TAG}/cmt-corrected-no-tools.json'
    jobs['cmt'] = [sys.executable, '-u', str(ROOT / 'analysis/CMT-Benchmark/evaluate.py'),
        '--dataset', str(ROOT / 'analysis/CMT-Benchmark/data/cmt_data_clean.json'),
        '--ids-file', str(SOURCE / 'cmt-corrected-ids.json'), *common,
        '--rounds', '4', '--aggregation', 'mean', '--num-workers', str(workers),
        '--timeout', '1800', '--no-use-tools', '--web-search', 'disabled',
        '--output', str(cmt_output)]
    critpt_output = ROOT / f'analysis/CritPt/artifacts/{TAG}/critpt-corrected-no-tools.json'
    jobs['critpt'] = [sys.executable, '-u', str(ROOT / 'analysis/CritPt/scripts/evaluate.py'),
        '--dataset', 'corrected', *common, '--rounds', '4', '--aggregation', 'mean',
        '--num-workers', str(workers), '--round-workers', '2', '--timeout', '3600',
        '--limit-policy', 'incorrect', '--no-use-tools', '--web-search', 'disabled',
        '--output', str(critpt_output)]
    return jobs


def summary_path(benchmark: str, command: list[str]) -> Path:
    output = Path(command[command.index('--output') + 1])
    return output / 'summary.json' if benchmark in ORDER[:3] else output.with_suffix('.summary.json')


def report(output: Path, jobs: dict) -> dict:
    results = {}
    for benchmark in ORDER:
        path = summary_path(benchmark, jobs[benchmark])
        row = json.loads(path.read_text()) if path.exists() else {'complete': False}
        if benchmark in ORDER[:3]:
            metrics = {'pass@1': row.get('accuracy')}
        else:
            metrics = {'mean@4': row.get('mean_score'), 'pass@4': row.get('max_score')}
        results[benchmark] = {'complete': bool(row.get('complete')), 'summary': str(path),
                              'questions': row.get('questions'), **metrics}
    completed = [name for name in ORDER if results[name]['complete']]
    active = next((name for name in ORDER if name not in completed), None)
    value = {'updated_at': datetime.now(timezone.utc).isoformat(),
             'complete': len(completed) == len(ORDER), 'model': MODEL,
             'reasoning_effort': 'high', 'judge_model': JUDGE,
             'judge_reasoning_effort': 'high', 'tools': False,
             'order': list(ORDER), 'completed_benchmarks': completed,
             'active_or_next': active, 'results': results}
    atomic_json(output / 'summary.json', value)
    lines = ['# GPT-5.6-Luna High — corrected evaluations', '',
             'No tools. Fable 5 High judges every saved Luna answer. Benchmarks run sequentially in the listed order.', '',
             '| Benchmark | Questions | Metric | Score | Status |',
             '|---|---:|---|---:|---|']
    for benchmark, row in results.items():
        for metric in ('pass@1', 'mean@4', 'pass@4'):
            if metric not in row:
                continue
            score = '—' if row[metric] is None else f"{100 * row[metric]:.2f}%"
            status = 'complete' if row['complete'] else ('active/next' if benchmark == active else 'queued')
            lines.append(f"| {benchmark} | {row['questions'] or '—'} | {metric} | {score} | {status} |")
    lines += ['', f"Updated: {value['updated_at']}", '']
    temporary = output / 'RESULTS.md.tmp'
    temporary.write_text('\n'.join(lines))
    temporary.replace(output / 'RESULTS.md')
    return value


def execute(benchmark: str, command: list[str], output: Path, retries: int) -> int:
    log = output / 'logs' / f'{benchmark}.log'
    for invocation in range(1, retries + 2):
        with log.open('a') as stream:
            stream.write(f'\nInvocation {invocation}: {json.dumps(command)}\n')
            stream.flush()
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode == 0:
            return 0
        if invocation <= retries:
            time.sleep(30)
    return result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=ROOT / f'model_evals/luna/runs/{TAG}')
    parser.add_argument('--workers', type=int, default=24)
    parser.add_argument('--retries', type=int, default=3)
    parser.add_argument('--stage', choices=['prepare', 'all', 'summary'], default='all')
    args = parser.parse_args(argv)
    if args.workers < 1 or args.retries < 0:
        parser.error('Workers must be positive and retries nonnegative')
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'logs').mkdir(exist_ok=True)
    with (args.output / '.suite.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        jobs = commands(args.output, args.workers)
        if args.stage == 'summary':
            return 0 if report(args.output, jobs)['complete'] else 2
        rejudge = json.loads(REJUDGE.read_text()) if REJUDGE.exists() else {}
        if not rejudge.get('complete'):
            raise ValueError('Finish the Gemini Sol re-judging run before starting Luna')
        manifest = {'version': 1, 'model': MODEL, 'reasoning_effort': 'high',
                    'judge_model': JUDGE, 'judge_reasoning_effort': 'high', 'tools': False,
                    'order': list(ORDER), 'commands': jobs,
                    'source_sha256': {
                        **{str(GEMINI_RUN / benchmark / 'corrected/dataset.json'):
                           file_hash(GEMINI_RUN / benchmark / 'corrected/dataset.json')
                           for benchmark in ORDER[:3]},
                        **{str(SOURCE / name): file_hash(SOURCE / name)
                           for name in ('hle-corrected.json', 'cmt-corrected-ids.json')}},
                    'implementation_sha256': file_hash(Path(__file__))}
        manifest_path = args.output / 'manifest.json'
        if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
            progress = report(args.output, jobs)
            if progress['completed_benchmarks']:
                raise ValueError('Suite implementation or inputs changed after evaluation began')
            previous = json.loads(manifest_path.read_text())
            history = args.output / 'manifest-history' / f'{fingerprint(previous)}.json'
            history.parent.mkdir(exist_ok=True)
            require_checkpoint(history, previous)
            atomic_json(manifest_path, manifest)
        else:
            require_checkpoint(manifest_path, manifest)
        report(args.output, jobs)
        if args.stage == 'prepare':
            print(json.dumps(manifest, indent=2))
            return 0
        atomic_json(args.output / 'supervisor.json', {'pid': os.getpid(), 'state': 'running'})
        for benchmark in ORDER:
            current = report(args.output, jobs)
            if current['results'][benchmark]['complete']:
                continue
            atomic_json(args.output / 'supervisor.json', {
                'pid': os.getpid(), 'state': 'running', 'benchmark': benchmark})
            print(f'Starting {benchmark}', flush=True)
            code = execute(benchmark, jobs[benchmark], args.output, args.retries)
            current = report(args.output, jobs)
            if code or not current['results'][benchmark]['complete']:
                atomic_json(args.output / 'supervisor.json', {
                    'pid': os.getpid(), 'state': 'pending', 'benchmark': benchmark,
                    'returncode': code})
                return 2
            print(f'Completed {benchmark}', flush=True)
        value = report(args.output, jobs)
        atomic_json(args.output / 'supervisor.json', {'pid': os.getpid(), 'state': 'complete'})
        return 0 if value['complete'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
