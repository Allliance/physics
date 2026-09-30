#!/usr/bin/env python3
"""Run the Gemini/Sol comparison protocols concurrently with resumable outputs."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from eval.storage import atomic_json, file_hash, require_checkpoint


def load_credentials():
    """Read existing standalone key assignments without executing shell startup code."""
    if os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY'):
        return
    path = Path.home() / '.bashrc'
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                words = shlex.split(line, comments=True)
            except ValueError:
                continue
            if words and words[0] == 'export':
                words = words[1:]
            if len(words) == 1 and '=' in words[0]:
                key, value = words[0].split('=', 1)
                if key in {'GOOGLE_API_KEY', 'GEMINI_API_KEY'} and value and not any(
                        token in value for token in ('$', '`')):
                    os.environ.setdefault(key, value)
    if not (os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY')):
        raise ValueError('Set GOOGLE_API_KEY or GEMINI_API_KEY before launching')


def commands(args):
    jobs = {}
    for benchmark in ('phybench', 'prism', 'ugphysics'):
        output = args.output_dir / benchmark / 'initial'
        initial = [sys.executable, '-u', str(Path(__file__).with_name('evaluate_initial.py')),
                   benchmark, '--scope', args.scope, '--output', str(output),
                   '--workers', str(args.workers), '--max-output-tokens', '65536']
        corrected = [sys.executable, '-u', '-m', 'eval', '--dataset', benchmark,
                     '--model', 'gemini-3.1-pro-preview', '--judge-model', 'claude-fable-5',
                     '--judge-reasoning-effort', 'high', '--reasoning-effort', 'high',
                     '--mode', 'merged', '--predictions-from', str(output / 'corrected-import'),
                     '--output', str(output.parent / 'corrected'),
                     '--workers', str(args.judge_workers), '--timeout', '1800']
        jobs[benchmark] = {'initial': initial, 'corrected': corrected}
    jobs['repeated'] = {'all': [sys.executable, '-u', str(Path(__file__).with_name('repeated.py')),
                              '--output-dir', str(args.output_dir / 'repeated'),
                              '--tools', args.tools, '--workers', str(args.repeat_workers)]}
    return jobs


def record_provenance(directory):
    saved_path = directory / 'provenance.json'
    saved = json.loads(saved_path.read_text()) if saved_path.exists() else {}
    files = [ROOT / 'utils/gemini_backend.py', Path(__file__).with_name('evaluate_initial.py')]
    for package in ('eval', 'benchmarks/hle/hle_eval', 'analysis/CMT-Benchmark/cmt_eval',
                    'analysis/CritPt/scripts/critpt_eval'):
        files.extend(p for p in (ROOT / package).rglob('*')
                     if p.is_file() and p.suffix in {'.py', '.txt', '.json'} and '__pycache__' not in p.parts
                     and 'artifacts' not in p.parts and 'tests' not in p.parts)
    # Result reports added beside eval/ are outputs, not evaluator inputs.
    # Retain previously pinned entries so existing ledgers remain comparable.
    files = [p for p in files if p.suffix != '.json' or 'prompts' in p.parts
             or str(p.relative_to(ROOT)) in saved.get('evaluator_sha256', {})]
    value = {'evaluator_sha256': {str(p.relative_to(ROOT)): file_hash(p) for p in sorted(set(files))},
             'timeouts': {'hle_cmt_seconds': 1800, 'critpt_seconds': 3600,
                          'semantics': 'Gemini transport inactivity; errors remain pending, not a Sol session wall deadline'},
             'reasoning': {'default': 'high', 'critpt_requested': 'max', 'critpt_effective': 'high'},
             'tools': 'Google native Python execution and Google Search; server-managed tool limits'}
    require_checkpoint(directory / 'provenance.json', value)


def report(directory):
    results = {}
    for benchmark in ('phybench', 'prism', 'ugphysics'):
        results[benchmark] = {}
        for split in ('initial', 'corrected'):
            path = directory / benchmark / split / 'summary.json'
            results[benchmark][split] = json.loads(path.read_text()) if path.exists() else {'complete': False}
    repeated = directory / 'repeated' / 'suite-summary.json'
    results['repeated'] = json.loads(repeated.read_text()) if repeated.exists() else {'complete': False}
    complete = all(results[b][s].get('complete') for b in ('phybench', 'prism', 'ugphysics')
                   for s in ('initial', 'corrected')) and bool(results['repeated'].get('complete'))
    value = {'updated_at': datetime.now(timezone.utc).isoformat(), 'complete': complete,
             'model': 'gemini-3.1-pro-preview', 'results': results}
    atomic_json(directory / 'summary.json', value)
    return value


def execute(argv, log_path, retries):
    for attempt in range(retries + 1):
        with log_path.open('a') as log:
            log.write(f'\nInvocation {attempt + 1}: {shlex.join(argv)}\n')
            log.flush()
            result = subprocess.run(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode == 0:
            return 0
        if attempt < retries:
            time.sleep(30)
    return result.returncode


def await_existing(name, args):
    """Adopt only an existing evaluator targeting this exact output directory."""
    pid_file = args.output_dir / f'{name}.pid'
    if not args.adopt_running or not pid_file.exists():
        return
    pid = int(pid_file.read_text().strip())
    process = Path('/proc') / str(pid)
    if not process.exists():
        return
    command = (process / 'cmdline').read_bytes().decode().rstrip('\0').split('\0')
    output = str(args.output_dir / 'repeated' if name == 'repeated'
                 else args.output_dir / name / 'initial')
    flag = '--output-dir' if name == 'repeated' else '--output'
    if flag not in command or command[command.index(flag) + 1] != output:
        raise ValueError(f'Refusing to adopt unrelated PID {pid}')
    expected = 'model_evals.gemini.repeated' if name == 'repeated' else 'evaluate_initial.py'
    if not any(expected in part or (name == 'repeated' and part.endswith('/repeated.py'))
               for part in command):
        raise ValueError(f'PID {pid} is not the expected evaluator')
    def identity():
        fields = (process / 'stat').read_text().rsplit(')', 1)[1].split()
        return fields[0], fields[19]
    _, started = identity()
    print(f'Adopting {name} PID {pid}', flush=True)
    while True:
        try:
            state, current = identity()
        except FileNotFoundError:
            return
        if state == 'Z' or current != started:
            return
        time.sleep(5)


def run_job(name, job, args):
    logs = args.output_dir / 'logs'
    await_existing(name, args)
    if name == 'repeated':
        return execute(job['all'] + ['--stage', 'all'], logs / 'repeated.log', args.retries)
    status = execute(job['initial'], logs / f'{name}-initial.log', args.retries)
    if status:
        return status
    return execute(job['corrected'], logs / f'{name}-corrected.log', args.retries)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--scope', choices=['selected', 'sol', 'full'], default='selected')
    p.add_argument('--tools', choices=['none'], default='none')
    p.add_argument('--workers', type=int, default=16)
    p.add_argument('--repeat-workers', type=int, default=32)
    p.add_argument('--judge-workers', type=int, default=8)
    p.add_argument('--retries', type=int, default=3)
    p.add_argument('--adopt-running', action='store_true',
                   help='Wait for verified evaluators in BENCHMARK.pid files, then resume them')
    p.add_argument('--stage', choices=['prepare', 'all', 'summary'], default='all')
    args = p.parse_args()
    if min(args.workers, args.repeat_workers, args.judge_workers) < 1 or args.retries < 0:
        p.error('Worker counts must be positive and retries nonnegative')
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'logs').mkdir(exist_ok=True)
    with (args.output_dir / '.suite.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        jobs = commands(args)
        if args.stage == 'summary':
            value = report(args.output_dir)
            print(json.dumps(value, indent=2))
            return 0 if value['complete'] else 2
        record_provenance(args.output_dir)
        atomic_json(args.output_dir / 'commands.json', jobs)
        if args.stage == 'prepare':
            statuses = {}
            for name, job in jobs.items():
                argv = job['all'] if name == 'repeated' else job['initial']
                statuses[name] = execute(argv + ['--stage', 'prepare'],
                                         args.output_dir / 'logs' / f'{name}-prepare.log', 0)
            atomic_json(args.output_dir / 'prepare-status.json', statuses)
            print(json.dumps(statuses))
            return int(any(statuses.values()))
        load_credentials()
        statuses = {name: 'running' for name in jobs}
        atomic_json(args.output_dir / 'job-status.json', statuses)
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = {pool.submit(run_job, name, job, args): name for name, job in jobs.items()}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    statuses[name] = future.result()
                except Exception as exc:
                    statuses[name] = f'{type(exc).__name__}: {exc}'
                atomic_json(args.output_dir / 'job-status.json', statuses)
                report(args.output_dir)
                print(f'{name}: {statuses[name]}', flush=True)
        value = report(args.output_dir)
        return 0 if value['complete'] and all(v == 0 for v in statuses.values()) else 2


if __name__ == '__main__':
    raise SystemExit(main())
