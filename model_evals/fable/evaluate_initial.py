#!/usr/bin/env python3
"""Evaluate Fable 5 High on the frozen, unfiltered 100-item audit subsets."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import multiprocessing
import os
import signal
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from utils.fable_backend import (
    make_fable_client, parse_fable_response, resolve_fable_model,
)

NATIVE = None


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def atomic_json(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    tmp.replace(path)


def append(path, value):
    with path.open('a') as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + '\n')


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def native(benchmark):
    global NATIVE
    if NATIVE is None:
        path = ROOT / {
            'ugphysics': 'benchmarks/ugphysics/auxiliary_judge_codex.py',
            'prism': 'benchmarks/prism/scripts/run_codex_rounds.py',
            'phybench': 'benchmarks/phybench/evaluate_codex.py',
        }[benchmark]
        NATIVE = load_module('fable_native_runner', path)
    return NATIVE


def validate_selection(selected, manifest, benchmark):
    ids = [row['problem_id'] for row in selected]
    expected = manifest['benchmarks'][benchmark]['selected_problem_ids']
    if len(ids) != 100 or len(set(ids)) != 100 or ids != expected:
        raise ValueError('Selection must match the original 100 unique IDs in manifest order')
    return ids


def check_checkpoint(path, expected):
    if path.exists():
        if json.loads(path.read_text()) != expected:
            raise ValueError(f'Checkpoint configuration changed: use a new output directory ({path})')
    else:
        atomic_json(path, expected)


def prepare(args):
    source = ROOT / 'audit/initial_data/selected' / args.benchmark / 'responses.jsonl'
    selected = read_jsonl(source)
    selection_manifest = json.loads((source.parent.parent / 'selection-manifest.json').read_text())
    ids = validate_selection(selected, selection_manifest, args.benchmark)
    runner = native(args.benchmark)
    if args.benchmark == 'ugphysics':
        from utils import make_prompt
        original = read_jsonl(ROOT / 'benchmarks/ugphysics/artifacts/gpt-5.6-sol-high-random-1000/sample.jsonl')
        by_id = {row['_eval_id']: row for row in original}
        system = ('Solve the supplied undergraduate physics problem yourself. Give a rigorous, '
                  'self-contained solution and obey its requested answer format. Do not use tools, '
                  'files, web search, or external context.')
        prompt_builder = lambda row: f"{make_prompt(row)}\n\n{row['problem']}"
        context_builder = lambda row: row['problem']
        reference_builder = lambda row: f"{row['solution']}\n\nReference answer:\n{row['answers']}"
    elif args.benchmark == 'phybench':
        original = runner.load_rows()
        by_id = {str(row['id']): {**row, '_eval_id': str(row['id'])} for row in original}
        system = runner.SYSTEM_PROMPT
        prompt_builder = lambda row: row['content']
        context_builder = lambda row: row['content']
        reference_builder = lambda row: row['solution']
    else:
        from utils.prompt_utils import get_problem_context, get_reference_solution
        original = runner.load_text_problems(ROOT / 'benchmarks/prism/datasets')
        by_id = {row['_eval_id']: row for row in original}
        system = ('Answer using only the supplied prompt. Do not use tools, shell commands, '
                  'files, web search, or external context.')
        prompt_builder = runner.get_eval_prompt
        context_builder = get_problem_context
        reference_builder = get_reference_solution
    rows = []
    for audit in selected:
        row = by_id[audit['problem_id']]
        if context_builder(row).strip() != audit['problem_statement'].strip():
            raise ValueError(f"Original question differs from selected export: {audit['problem_id']}")
        if reference_builder(row).strip() != audit['reference_solution'].strip():
            raise ValueError(f"Original reference differs from selected export: {audit['problem_id']}")
        rows.append({'id': row['_eval_id'], 'native': row,
                     'system_prompt': system, 'prompt': prompt_builder(row)})
    config = {
        'benchmark': args.benchmark, 'model': 'claude-fable-5',
        'api_model': resolve_fable_model(None), 'reasoning_effort': 'high',
        'thinking': 'adaptive', 'tools': False, 'attempts_per_question': 1,
        'max_output_tokens': args.max_output_tokens,
        'judge_model': 'gpt-5.6-sol' if args.benchmark == 'ugphysics' else None,
        'judge_reasoning_effort': 'high' if args.benchmark == 'ugphysics' else None,
        'source': str(source.relative_to(ROOT)),
        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'evaluated_ids': ids, 'sample_sha256': digest(rows),
        'problem_count': 100, 'excluded_count': 0,
        'evaluation': {
            'ugphysics': 'native auto_judge, then released auxiliary equivalence judge on non-passes',
            'prism': 'native PRISM final-answer DAG matches',
            'phybench': 'native EED score == 100, with original presentation-only normalization',
        }[args.benchmark],
        'grader_sources': {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / 'benchmarks' / args.benchmark /
                             {'ugphysics': 'codes', 'prism': 'utils', 'phybench': 'EED'}[args.benchmark]).glob('*.py'))
        },
    }
    if args.benchmark == 'ugphysics':
        config['judge_prompt_sha256'] = hashlib.sha256(runner.JUDGE_PROMPT_PATH.read_bytes()).hexdigest()
    elif args.benchmark == 'phybench':
        config['answer_schema'] = runner.SCHEMA
        runner_path = ROOT / 'benchmarks/phybench/evaluate_codex.py'
        config['grader_sources'][str(runner_path.relative_to(ROOT))] = hashlib.sha256(runner_path.read_bytes()).hexdigest()
    args.output.mkdir(parents=True, exist_ok=True)
    check_checkpoint(args.output / 'manifest.json', config)
    check_checkpoint(args.output / 'sample.json', rows)
    return rows, config


def records(args, filename, ids):
    rows = read_jsonl(args.output / filename)
    result = {r['id']: r for r in rows}
    if len(result) != len(rows) or set(result) - set(ids):
        raise ValueError(f'Duplicate or unexpected IDs in {filename}')
    return result


def parse_final_answer(text):
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != {'final_answer'} or not isinstance(value['final_answer'], str):
        raise ValueError('Expected a JSON object containing only a string final_answer')
    return value['final_answer']


def generate_one(row, config, timeout):
    client = make_fable_client(timeout)
    try:
        output_config = {'effort': 'high'}
        if 'answer_schema' in config:
            output_config['format'] = {'type': 'json_schema', 'schema': config['answer_schema']}
        with client.messages.stream(
            model=config['api_model'], max_tokens=config['max_output_tokens'],
            system=row['system_prompt'], messages=[{'role': 'user', 'content': row['prompt']}],
            thinking={'type': 'adaptive'}, output_config=output_config,
        ) as stream:
            raw = stream.get_final_message().model_dump(mode='json')
        result = parse_fable_response(raw, config['api_model'])
        if 'answer_schema' in config:
            result['final_answer'] = ''
            result['answer_format_error'] = None
            if not result['refused']:
                try:
                    result['final_answer'] = parse_final_answer(result['response'])
                except (ValueError, TypeError) as exc:
                    # Retain malformed completed outcomes as non-passes; never resample them.
                    result['answer_format_error'] = str(exc)
        return {'id': row['id'], **result, 'raw_response': raw,
                'prompt_sha256': digest([row['system_prompt'], row['prompt']]), 'created_at': now()}
    finally:
        client.close()


def grade_child(connection, benchmark, row, response, timeout):
    os.setsid()
    if hasattr(os, 'sched_getaffinity'):
        os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:4])
    try:
        runner = native(benchmark)
        if benchmark == 'ugphysics':
            judge = runner.Judger(strict_extract=True)
            result = {'correct': bool(judge.auto_judge(response, row['answers'], precision=1e-2)),
                      'extracted_answer': judge.extract_ans(response), 'reference_answer': row['answers']}
        elif benchmark == 'phybench':
            result = runner.score(row, {'final_answer': response})
            result['correct'] = result.pop('success')
        else:
            result = runner.grade_one(row, {'response': response}, timeout)
            result['correct'] = result.pop('final_answer_correct')
        connection.send({**result, 'id': row['_eval_id'], 'grading_error': None})
    except Exception as exc:
        connection.send({'id': row['_eval_id'], 'correct': False,
                         'grading_error': f'{type(exc).__name__}: {exc}'})
    finally:
        connection.close()


def grade_one(benchmark, row, response, timeout):
    started = time.monotonic()
    ctx = multiprocessing.get_context('fork')
    receiver, sender = ctx.Pipe(duplex=False)
    child = ctx.Process(target=grade_child, args=(sender, benchmark, row, response, timeout))
    child.start()
    sender.close()
    try:
        if receiver.poll(timeout + 5):
            result = receiver.recv()
        else:
            result = {'id': row['_eval_id'], 'correct': False,
                      'grading_error': f'Native grading timeout after {timeout:g}s'}
    finally:
        child.join(1)
        if child.is_alive():
            os.killpg(child.pid, signal.SIGKILL)
            child.join()
        receiver.close()
    return {**result, 'grading_seconds': time.monotonic() - started, 'created_at': now()}


def run_stage(args, rows, config, stage):
    ids = [row['id'] for row in rows]
    generations = records(args, 'generations.jsonl', ids)
    scores = records(args, 'scores.jsonl', ids)
    auxiliary = records(args, 'auxiliary_judgments.jsonl', ids)
    if stage == 'generate':
        pending = [row for row in rows if row['id'] not in generations]
        executor = ThreadPoolExecutor(max_workers=args.workers)
        function = lambda row: (generate_one, (row, config, args.timeout))
        output = 'generations.jsonl'
    elif stage == 'score':
        pending = [row for row in rows if row['id'] in generations and row['id'] not in scores]
        executor = ProcessPoolExecutor(max_workers=args.score_workers,
                                       mp_context=multiprocessing.get_context('fork'))
        function = lambda row: (grade_one, (args.benchmark, row['native'],
                                          generations[row['id']].get('final_answer', generations[row['id']]['response']),
                                          args.grade_timeout))
        output = 'scores.jsonl'
    else:
        if args.benchmark != 'ugphysics':
            return
        pending = [row for row in rows if row['id'] in scores and not scores[row['id']]['correct']
                   and row['id'] not in auxiliary]
        runner = native(args.benchmark)
        template = runner.JUDGE_PROMPT_PATH.read_text()
        executor = ThreadPoolExecutor(max_workers=args.workers)
        function = lambda row: (runner.judge_one, (row['native'],
                                {'completion': generations[row['id']]['response']}, template,
                                'gpt-5.6-sol', 'high', args.timeout))
        output = 'auxiliary_judgments.jsonl'
    if args.limit:
        pending = pending[:args.limit]
    print(f'{args.benchmark} {stage}: {len(pending)} pending', flush=True)
    with executor as pool:
        futures = {}
        for row in pending:
            fn, params = function(row)
            futures[pool.submit(fn, *params)] = row['id']
        for index, future in enumerate(as_completed(futures), 1):
            item_id = futures[future]
            try:
                item = future.result()
                append(args.output / output, item)
                print(f'{stage} {index}/{len(pending)} {item_id}: '
                      f"{item.get('correct', item.get('stop_reason'))}", flush=True)
            except Exception as exc:
                append(args.output / 'errors.jsonl', {'id': item_id, 'stage': stage,
                       'error': f'{type(exc).__name__}: {exc}', 'created_at': now()})
                print(f'{stage} FAILED {item_id}: {type(exc).__name__}: {exc}', flush=True)


def summarize(args, rows, config):
    ids = [row['id'] for row in rows]
    generations = records(args, 'generations.jsonl', ids)
    scores = records(args, 'scores.jsonl', ids)
    auxiliary = records(args, 'auxiliary_judgments.jsonl', ids)
    pending_aux = [i for i, s in scores.items() if not s['correct'] and i not in auxiliary]
    complete = len(generations) == len(scores) == len(ids) and (
        args.benchmark != 'ugphysics' or not pending_aux)
    rule_correct = sum(s['correct'] for s in scores.values())
    correct = sum(bool(scores.get(i, {}).get('correct') or auxiliary.get(i, {}).get('correct')) for i in ids)
    result = {
        'benchmark': args.benchmark, 'model': 'claude-fable-5', 'reasoning_effort': 'high',
        'tools': False, 'metric': 'initial pass@1', 'total': len(ids),
        'generated': len(generations), 'scored': len(scores), 'complete': complete,
        'rule_correct': rule_correct, 'initial_correct': correct if complete else None,
        'initial_accuracy': correct / len(ids) if complete else None,
        'auxiliary_judged': len(auxiliary), 'auxiliary_accepted': sum(s['correct'] for s in auxiliary.values()),
        'judge_model': config['judge_model'], 'judge_reasoning_effort': config['judge_reasoning_effort'],
        'refused_ids': [i for i, g in generations.items() if g.get('refused')],
        'answer_format_errors': [i for i, g in generations.items() if g.get('answer_format_error')],
        'grading_errors': [i for i, s in scores.items() if s.get('grading_error')],
        'missing_generation_ids': [i for i in ids if i not in generations],
        'missing_score_ids': [i for i in ids if i not in scores],
        'missing_auxiliary_ids': pending_aux if args.benchmark == 'ugphysics' else [],
        'updated_at': now(),
    }
    atomic_json(args.output / 'summary.json', result)
    print(json.dumps(result, indent=2), flush=True)
    return complete


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('benchmark', choices=['ugphysics', 'prism', 'phybench'])
    parser.add_argument('--stage', choices=['prepare', 'generate', 'score', 'auxiliary', 'summary', 'all'], default='all')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--score-workers', type=int, default=4)
    parser.add_argument('--timeout', type=float, default=1800)
    parser.add_argument('--grade-timeout', type=float, default=180)
    parser.add_argument('--max-output-tokens', type=int, default=32768)
    parser.add_argument('--limit', type=int, help='Limit pending work for a smoke test; retain the full sample manifest.')
    args = parser.parse_args()
    if args.output is None:
        args.output = (ROOT / 'benchmarks/phybench/artifacts/fable-5-high-initial-100'
                       if args.benchmark == 'phybench' else
                       Path(__file__).resolve().parent / 'runs' / f'{args.benchmark}-initial-high-100')
    rows, config = prepare(args)
    stages = ['generate', 'score', 'auxiliary'] if args.stage == 'all' else [args.stage]
    for stage in stages:
        if stage in {'generate', 'score', 'auxiliary'}:
            run_stage(args, rows, config, stage)
    complete = summarize(args, rows, config)
    return 0 if complete or args.limit or args.stage != 'all' else 1


if __name__ == '__main__':
    raise SystemExit(main())
