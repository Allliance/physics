"""Dataset-independent preparation, generation, judging, and reporting stages."""

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import fcntl
import json
import os
from pathlib import Path
import shutil
import sys
from datetime import datetime, timezone

from utils.fable_backend import resolve_fable_model
from .backends import make_judge, make_predictor, validate_judgment
from .datasets import AUDITED, load_dataset, predictor_input
from .scoring import summarize
from .storage import atomic_json, file_hash, fingerprint, require_checkpoint


def parser():
    p = argparse.ArgumentParser(description='Post-audit evaluation with the unified HLE-adapted judge.')
    p.add_argument('--dataset', required=True, help='A built-in benchmark, all, or a custom name with --data')
    p.add_argument('--data', type=Path, help='Local JSON, JSONL, or parquet; overrides built-in source')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--attempts', type=int, default=1,
                   help='Independent attempts per question (use 4 for paper-style mean@4/pass@4)')
    p.add_argument('--model', choices=['claude-fable-5', 'gpt-5.6-sol', 'gpt-5.6-luna',
                                      'gpt-oss-120b', 'kimi-k3', 'glm-5.3',
                                      'deepseek-v4-pro',
                                      'gpt-6-astra', 'gemini-3.1-pro-preview'],
                   default='claude-fable-5')
    p.add_argument('--reasoning-effort', choices=['low', 'medium', 'high', 'max'], default='high')
    p.add_argument('--judge-model', choices=['gpt-5.6-sol', 'gpt-6-astra', 'claude-fable-5'], default='gpt-5.6-sol')
    p.add_argument('--judge-max-output-tokens', type=int, default=8192)
    p.add_argument('--judge-reasoning-effort', choices=['low', 'medium', 'high'], default='high')
    p.add_argument('--mode', choices=['merged'], default='merged')
    p.add_argument('--fable-model', help='Configured Fable API alias')
    p.add_argument('--codex-bin', default=shutil.which('codex') or str(Path.home() / '.local/bin/codex'))
    p.add_argument('--max-output-tokens', type=int, default=32768)
    p.add_argument('--timeout', type=float, default=600)
    p.add_argument('--workers', type=int, default=6)
    p.add_argument('--max-pending', type=int, help='Cap pending work per stage for a smoke test; preserves the full denominator')
    p.add_argument('--stage', choices=['prepare', 'generate', 'judge', 'summary', 'all'], default='all')
    p.add_argument('--dry-run', action='store_true', help='Validate and describe inputs without writing or calling models')
    return p


def read_checkpoint(path, ids):
    value = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(value, dict) or set(value) - set(ids):
        raise ValueError(f'Checkpoint has unexpected question IDs: {path}')
    return value


def work(args, rows, checkpoint, filename, action):
    pending = [row for row in rows if row['id'] not in checkpoint]
    if args.max_pending is not None:
        pending = pending[:args.max_pending]
    if not pending:
        return
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(action, row): row['id'] for row in pending}
        for future in as_completed(futures):
            qid = futures[future]
            try:
                value = future.result()
            except Exception as exc:
                error = {'id': qid, 'stage': filename, 'error': f'{type(exc).__name__}: {exc}',
                         'time': datetime.now(timezone.utc).isoformat()}
                with (args.output / 'errors.jsonl').open('a') as handle:
                    handle.write(json.dumps(error) + '\n')
                print(f'{filename}: failed {qid}: {error["error"]}', file=sys.stderr, flush=True)
                continue
            checkpoint[qid] = value
            atomic_json(args.output / filename, checkpoint)
            print(f'{filename}: {len(checkpoint)}/{len(rows)} ({qid})', flush=True)


def write_report(args, rows, selection, predictions, judgments):
    summary = summarize(rows, predictions, judgments)
    summary.update(dataset=selection['dataset'], split=selection['split'], model=args.model,
                   reasoning_effort=args.reasoning_effort, judge_model=args.judge_model,
                   judge_reasoning_effort=args.judge_reasoning_effort, tools=False,
                   evaluator='HLE-adapted physics equivalence; merged binary score',
                   source_count=selection['source_count'], excluded_count=len(selection['excluded']))
    atomic_json(args.output / 'summary.json', summary)
    with (args.output / 'per_question_results.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['id', 'correct', 'extracted_final_answer', 'reasoning'])
        writer.writeheader()
        for row in summary['per_question']:
            judgment = judgments.get(row['id'], {}).get('judgment', {})
            writer.writerow({**row, **{k: judgment.get(k, '') for k in ['extracted_final_answer', 'reasoning']}})
    print(json.dumps({k: v for k, v in summary.items() if k != 'per_question'}, indent=2), flush=True)
    return summary


def run_one(args):
    if min(args.workers, args.max_output_tokens, args.judge_max_output_tokens, args.timeout) <= 0 or (args.max_pending is not None and args.max_pending <= 0):
        raise ValueError('Worker, token, timeout, and pending limits must be positive')
    if args.model == args.judge_model:
        raise ValueError('Choose a judge different from the evaluated model')
    rows, selection = load_dataset(args.dataset, data=args.data, split='post-audit')
    api_model = resolve_fable_model(args.fable_model) if args.model == 'claude-fable-5' else None
    package = Path(__file__).parent
    manifest = {
        'version': 1, 'selection': selection, 'model': args.model, 'reasoning_effort': args.reasoning_effort,
        'judge_model': args.judge_model, 'judge_reasoning_effort': args.judge_reasoning_effort,
        'mode': 'merged', 'tools': False, 'attempts_per_question': 1,
        'generation': {
            'api_model': api_model, 'max_output_tokens': args.max_output_tokens,
            'route_sha256': fingerprint(os.environ.get('ANTHROPIC_BASE_URL', 'https://api.anthropic.com'))},
        'timeout': args.timeout, 'codex_bin': str(Path(args.codex_bin).resolve()),
        'implementation_sha256': {str(p.relative_to(package)): file_hash(p) for p in sorted(package.glob('*.py'))},
        'prompts_sha256': {p.name: file_hash(p) for p in sorted((package / 'prompts').iterdir()) if p.is_file()},
        'shared_backend_sha256': file_hash(package.parent / 'utils/fable_backend.py'),
    }
    if args.judge_model == 'claude-fable-5':
        manifest['judge_backend'] = {
            'api_model': resolve_fable_model(args.fable_model),
            'max_output_tokens': args.judge_max_output_tokens,
            'route_sha256': fingerprint(os.environ.get('ANTHROPIC_BASE_URL', 'https://api.anthropic.com')),
            'thinking': 'adaptive',
        }
    if args.model == 'gemini-3.1-pro-preview':
        from utils import gemini_backend
        manifest['gemini_backend_sha256'] = file_hash(Path(gemini_backend.__file__))
        manifest['generation']['thinking_level'] = args.reasoning_effort
    if args.model in {'gpt-oss-120b', 'kimi-k3', 'glm-5.3', 'deepseek-v4-pro'}:
        from utils.openai_compatible import backend_metadata
        manifest['generation'].update(backend_metadata())
    if args.dry_run:
        print(json.dumps(manifest, indent=2))
        return 0
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / '.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another process is using this output directory') from None
        if not (args.output / 'manifest.json').exists() and any(
                (args.output / name).exists() for name in ['predictions.json', 'judgments.json', 'dataset.json']):
            raise ValueError('Existing checkpoints lack a manifest; choose a new output directory')
        require_checkpoint(args.output / 'manifest.json', manifest)
        require_checkpoint(args.output / 'dataset.json', rows)
        require_checkpoint(args.output / 'selection.json', selection)
        ids = [row['id'] for row in rows]
        predictions = read_checkpoint(args.output / 'predictions.json', ids)
        judgments = read_checkpoint(args.output / 'judgments.json', ids)
        for qid, prediction in predictions.items():
            if not isinstance(prediction.get('response'), str) or not prediction['response'].strip():
                raise ValueError(f'Invalid prediction checkpoint: {qid}')
        for qid, result in judgments.items():
            validate_judgment(result.get('judgment'))
            if qid not in predictions or result['prediction_sha256'] != fingerprint(predictions[qid]):
                raise ValueError(f'Prediction changed after judging: {qid}')
        if args.stage in {'all', 'generate'} and len(predictions) < len(rows):
            predict = make_predictor(args, api_model)
            work(args, rows, predictions, 'predictions.json', lambda row: predict(predictor_input(row)))
        if args.stage in {'all', 'judge'} and any(qid not in judgments for qid in predictions):
            judge = make_judge(args)

            def judge_one(row):
                prediction = predictions[row['id']]
                result = judge(row, prediction)
                validate_judgment(result['judgment'])
                return {**result, 'prediction_sha256': fingerprint(prediction)}

            work(args, [row for row in rows if row['id'] in predictions], judgments, 'judgments.json', judge_one)
        summary = write_report(args, rows, selection, predictions, judgments)
        return 0 if summary['complete'] or args.stage in {'prepare', 'generate'} else 2


def aggregate(args, datasets):
    result = {'protocol': 'post-audit', 'attempts': args.attempts,
              'model': args.model, 'benchmarks': {}}
    for dataset in datasets:
        rows, _ = load_dataset(dataset, data=args.data if len(datasets) == 1 else None,
                               split='post-audit')
        ids = [row['id'] for row in rows]
        outcomes = {qid: [] for qid in ids}
        complete = True
        for attempt in range(1, args.attempts + 1):
            path = args.output / dataset / f'attempt-{attempt}' / 'judgments.json'
            judgments = json.loads(path.read_text()) if path.exists() else {}
            complete &= len(judgments) == len(ids)
            for qid in ids:
                if qid in judgments:
                    outcomes[qid].append(judgments[qid]['judgment']['correct'] == 'yes')
        completed = sum(len(values) for values in outcomes.values())
        correct = sum(sum(values) for values in outcomes.values())
        result['benchmarks'][dataset] = {
            'questions': len(ids), 'completed_scores': completed, 'complete': complete,
            f'mean@{args.attempts}': correct / (len(ids) * args.attempts) if complete else None,
            f'pass@{args.attempts}': sum(any(values) for values in outcomes.values()) / len(ids)
            if complete else None,
        }
    atomic_json(args.output / 'summary.json', result)
    return result


def run(args):
    if args.attempts <= 0:
        raise ValueError('--attempts must be positive')
    requested = args.dataset.lower()
    if requested != 'all' and args.attempts == 1:
        return run_one(args)
    if requested == 'all' and args.data is not None:
        raise ValueError('--data cannot be combined with --dataset all')
    datasets = sorted(AUDITED | {'cmt', 'critpt'}) if requested == 'all' else [args.dataset]
    status = 0
    for dataset in datasets:
        for attempt in range(1, args.attempts + 1):
            child = copy.copy(args)
            child.dataset = dataset
            child.output = args.output / dataset / f'attempt-{attempt}'
            child.attempts = 1
            status = max(status, run_one(child))
    if not args.dry_run:
        summary = aggregate(args, datasets)
        print(json.dumps(summary, indent=2))
    return status


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return run(args)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
