#!/usr/bin/env python3
"""Evaluate Fable 5 High on the frozen, unfiltered 100-item audit subsets."""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from utils.fable_backend import (
    make_fable_client, parse_fable_response, resolve_fable_model,
)

from eval.pre_audit import native as released
from eval.pre_audit.pipeline import load_benchmark


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
    pipeline = load_benchmark(args.benchmark)
    by_id = {problem.id: problem for problem in pipeline.problems}
    rows = []
    for audit in selected:
        problem = by_id[audit['problem_id']]
        if problem.question.strip() != audit['problem_statement'].strip():
            raise ValueError(f"Original question differs from selected export: {problem.id}")
        if problem.reference_answer.strip() != audit['reference_solution'].strip():
            raise ValueError(f"Original reference differs from selected export: {problem.id}")
        rows.append({'id': problem.id, 'native': problem.native,
                     'system_prompt': problem.system_prompt or
                     'Answer using only the supplied prompt. Do not use tools, shell commands, '
                     'files, web search, or external context.', 'prompt': problem.prompt})
    provenance = released.provenance(args.benchmark)
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
        'grader_sources': {**provenance['sources_sha256'],
                           str(Path(released.__file__).relative_to(ROOT)): provenance['adapter_sha256']},
        'evaluator_source': provenance,
    }
    if args.benchmark == 'ugphysics':
        config['judge_prompt_sha256'] = hashlib.sha256(released.JUDGE_PROMPT_PATH.read_bytes()).hexdigest()
    elif args.benchmark == 'phybench':
        config['answer_schema'] = released.ANSWER_SCHEMA
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


def grade_one(benchmark, row, response, timeout):
    return {**released.grade_one(benchmark, row, response, timeout), 'created_at': now()}


def auxiliary_one(row, response, timeout):
    return {'id': row['_eval_id'],
            **released.auxiliary_judge(row, response, 'gpt-5.6-sol', timeout, 8192),
            'created_at': now()}


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
        executor = ThreadPoolExecutor(max_workers=args.workers)
        function = lambda row: (auxiliary_one, (row['native'],
                                generations[row['id']]['response'], args.timeout))
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
        args.output = (ROOT / 'model_evals/fable/artifacts/phybench-initial-100'
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
