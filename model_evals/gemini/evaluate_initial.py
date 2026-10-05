#!/usr/bin/env python3
"""Gemini pass@1 with the saved Sol native protocols and corrected-answer export."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Retain these imports before upstream PRISM/UGPhysics replace top-level utils.
from eval.datasets import load_dataset
from eval.storage import file_hash, fingerprint
from model_evals.fable import evaluate_initial as native_base
from eval.pre_audit import native as released
from eval.pre_audit.pipeline import load_benchmark
from utils.gemini_backend import generate as gemini_generate

MODEL = 'gemini-3.1-pro-preview'
atomic_json = native_base.atomic_json
check_checkpoint = native_base.check_checkpoint
read_jsonl = native_base.read_jsonl
append = native_base.append
records = native_base.records
now = native_base.now


def select_ids(scope, selected_ids, sol_ids, full_ids):
    ids = {'selected': selected_ids, 'sol': sol_ids, 'full': full_ids}[scope]
    if not ids or len(ids) != len(set(ids)) or not set(selected_ids).issubset(ids):
        raise ValueError('Evaluation scope must have unique IDs and include the audit selection')
    if not set(ids).issubset(full_ids):
        raise ValueError('Evaluation scope includes IDs absent from native sources')
    return ids


def prepare(args):
    source = ROOT / 'audit/initial_data/selected' / args.benchmark / 'responses.jsonl'
    selected = read_jsonl(source)
    selection_path = source.parent.parent / 'selection-manifest.json'
    selection_manifest = json.loads(selection_path.read_text())
    selected_ids = native_base.validate_selection(selected, selection_manifest, args.benchmark)
    pipeline = load_benchmark(args.benchmark)
    system = pipeline.problems[0].system_prompt or (
        'Answer using only the supplied prompt. Do not use tools, shell commands, '
        'files, web search, or external context.')
    archive = ROOT / 'benchmarks' / (args.benchmark + '_changed (discarded)')
    sources = [selection_path]
    if args.benchmark == 'phybench':
        dataset_path = archive / 'data/PHYBench-fullques_v1.json'
        sources.append(dataset_path)
        original = [{**row, '_eval_id': str(row['id'])}
                    for row in json.loads(dataset_path.read_text()) if row.get('content') and row.get('answer')]
        sol_ids = [row['_eval_id'] for row in original]
        prompt_builder = lambda row: row['content']
        context_builder = lambda row: row['content']
        reference_builder = lambda row: row['solution']
    else:
        data_dir = archive / ('datasets' if args.benchmark == 'prism' else 'data/dataset')
        prepared = released.historical_inputs(args.benchmark, data_dir)
        inputs = {item['native']['_eval_id']: item for item in prepared}
        original = [item['native'] for item in prepared]
        prompt_builder = lambda row: inputs[row['_eval_id']]['prompt']
        context_builder = lambda row: inputs[row['_eval_id']]['question']
        reference_builder = lambda row: inputs[row['_eval_id']]['reference_answer']
        if args.benchmark == 'ugphysics':
            sample_path = archive / 'artifacts/gpt-5.6-sol-high-random-1000/sample.jsonl'
            sol_ids = [row['_eval_id'] for row in read_jsonl(sample_path)]
            sources.extend(sorted(data_dir.glob('*/en.jsonl')))
            sources.append(sample_path)
        else:
            sol_manifest = archive / 'results_codex/gpt-5.6-sol_high/manifest.json'
            sol_ids = json.loads(sol_manifest.read_text())['problem_ids']
            sources.extend(sorted(data_dir.glob('*_cleaned_dag.json')))
            sources.append(sol_manifest)
    by_id = {row['_eval_id']: row for row in original}
    if len(by_id) != len(original):
        raise ValueError('Duplicate native problem IDs')
    for audit in selected:
        row = by_id[audit['problem_id']]
        if context_builder(row).strip() != audit['problem_statement'].strip():
            raise ValueError(f"Original question differs from audit selection: {audit['problem_id']}")
        if reference_builder(row).strip() != audit['reference_solution'].strip():
            raise ValueError(f"Original reference differs from audit selection: {audit['problem_id']}")
    ids = select_ids(args.scope, selected_ids, sol_ids, list(by_id))
    rows = [{'id': qid, 'native': by_id[qid], 'system_prompt': system,
             'prompt': prompt_builder(by_id[qid])} for qid in ids]
    provenance = released.provenance(args.benchmark)
    grader_sources = [Path(released.__file__), Path(__file__), Path(native_base.__file__),
                      ROOT / 'utils/gemini_backend.py']
    config = {
        'benchmark': args.benchmark, 'model': MODEL, 'api_model': MODEL,
        'reasoning_effort': 'high', 'effective_thinking_level': 'high', 'tools': False,
        'attempts_per_question': 1, 'max_output_tokens': args.max_output_tokens,
        'scope': args.scope, 'evaluated_ids': ids, 'problem_count': len(ids), 'excluded_count': 0,
        'audit_selected_count': len(selected_ids), 'sol_source_count': len(sol_ids),
        'full_native_count': len(original), 'sample_sha256': fingerprint(rows),
        'source': str(source.relative_to(ROOT)), 'source_sha256': file_hash(source),
        'sources': {str(p.relative_to(ROOT)): file_hash(p) for p in sources},
        'grader_sources': {**provenance['sources_sha256'],
                           **{str(p.relative_to(ROOT)): file_hash(p) for p in grader_sources}},
        'evaluator_source': provenance,
        'judge_model': 'gpt-5.6-sol' if args.benchmark == 'ugphysics' else None,
        'judge_reasoning_effort': 'high' if args.benchmark == 'ugphysics' else None,
        'evaluation': {
            'ugphysics': 'native auto_judge, then released auxiliary equivalence judge on non-passes',
            'prism': 'native PRISM final-answer DAG matches',
            'phybench': 'native EED score == 100, with original presentation-only normalization',
        }[args.benchmark],
    }
    if args.benchmark == 'ugphysics':
        config['judge_prompt_sha256'] = file_hash(released.JUDGE_PROMPT_PATH)
    elif args.benchmark == 'phybench':
        config['answer_schema'] = released.ANSWER_SCHEMA
    args.output.mkdir(parents=True, exist_ok=True)
    check_checkpoint(args.output / 'manifest.json', config)
    check_checkpoint(args.output / 'sample.json', rows)
    return rows, config


def generate_one(row, config, timeout, generate):
    result = generate(row['prompt'], system_prompt=row['system_prompt'], effort='high',
                      max_output_tokens=config['max_output_tokens'], timeout=timeout,
                      output_schema=config.get('answer_schema'))
    if 'answer_schema' in config:
        result['final_answer'] = ''
        result['answer_format_error'] = None
        if not result['refused']:
            try:
                result['final_answer'] = native_base.parse_final_answer(result['response'])
            except (ValueError, TypeError) as exc:
                # A completed format failure is an outcome, never grounds to resample.
                result['answer_format_error'] = str(exc)
    return {'id': row['id'], **result,
            'prompt_sha256': fingerprint([row['system_prompt'], row['prompt']]), 'created_at': now()}


def run_generation(args, rows, config, generate):
    done = records(args, 'generations.jsonl', [row['id'] for row in rows])
    pending = [row for row in rows if row['id'] not in done]
    if args.limit:
        pending = pending[:args.limit]
    print(f'{args.benchmark} generate: {len(pending)} pending', flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(generate_one, row, config, args.timeout, generate): row['id']
                   for row in pending}
        for index, future in enumerate(as_completed(futures), 1):
            qid = futures[future]
            try:
                append(args.output / 'generations.jsonl', future.result())
                print(f'generate {index}/{len(pending)} {qid}', flush=True)
            except Exception as exc:
                append(args.output / 'errors.jsonl', {'id': qid, 'stage': 'generate',
                       'error': f'{type(exc).__name__}: {exc}',
                       'partial_result': getattr(exc, 'result', None), 'created_at': now()})
                print(f'generate FAILED {qid}: {type(exc).__name__}: {exc}', flush=True)


def export_corrected(args, rows, config):
    corrected, selection = load_dataset(args.benchmark)
    samples = {row['id']: row for row in rows}
    generations = records(args, 'generations.jsonl', list(samples))
    imported = {}
    for row in corrected:
        qid = row['id']
        if qid not in generations:
            raise ValueError(f'Missing corrected-subset generation: {qid}')
        record = generations[qid]
        prompt_hash = fingerprint([samples[qid]['system_prompt'], samples[qid]['prompt']])
        if record.get('prompt_sha256') != prompt_hash:
            raise ValueError(f'{qid}: generation prompt checksum mismatch')
        if record.get('requested_model') != MODEL or record.get('tool_events'):
            raise ValueError(f'{qid}: generation model or tool configuration mismatch')
        if not (record.get('stop_reason') == 'STOP' or record.get('refused')):
            raise ValueError(f'{qid}: generation is incomplete')
        response = record.get('final_answer', record['response'])
        # Retain malformed/refused completed outcomes in corrected judging as well.
        if not response.strip():
            response = record['response']
        imported[qid] = {'response': response, 'requested_model': MODEL,
                         'actual_model': record['actual_model'], 'tool_events': [],
                         'refused': record.get('refused', False),
                         'requested_reasoning_effort': record.get('requested_reasoning_effort', 'high'),
                         'effective_thinking_level': record.get('effective_thinking_level', 'high'),
                         'usage': record.get('usage'),
                         'raw_artifact': str(args.output / 'generations.jsonl'),
                         'original_record_sha256': fingerprint(record),
                         'original_prompt_sha256': prompt_hash}
    manifest = {'format': 'normalized-predictions-v1', 'model': MODEL,
                'reasoning_effort': 'high', 'tools': False, 'attempt': 1,
                'selection': selection, 'original_scope': config['scope'],
                'original_sources': {str(args.output / name): file_hash(args.output / name)
                                     for name in ['manifest.json', 'sample.json', 'generations.jsonl']},
                'predictions_sha256': fingerprint(imported)}
    output = args.output / 'corrected-import'
    output.mkdir(exist_ok=True)
    for name, value in [('manifest.json', manifest), ('dataset.json', corrected),
                        ('predictions.json', imported)]:
        check_checkpoint(output / name, value)
    print(f'{args.benchmark}: exported {len(imported)} answers to {output}', flush=True)


def summarize(args, rows, config):
    # Native summary logic keeps non-passes and incomplete runs consistent across models.
    with contextlib.redirect_stdout(io.StringIO()):
        complete = native_base.summarize(args, rows, config)
    path = args.output / 'summary.json'
    result = json.loads(path.read_text())
    result.update(model=MODEL, scope=config['scope'])
    atomic_json(path, result)
    print(json.dumps(result, indent=2), flush=True)
    return complete


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('benchmark', choices=['phybench', 'prism', 'ugphysics'])
    parser.add_argument('--scope', choices=['selected', 'sol', 'full'], default='selected')
    parser.add_argument('--stage', choices=['prepare', 'generate', 'score', 'auxiliary', 'summary',
                                          'export-corrected', 'all'], default='all')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--score-workers', type=int, default=4)
    parser.add_argument('--timeout', type=float, default=1800)
    parser.add_argument('--grade-timeout', type=float, default=180)
    parser.add_argument('--max-output-tokens', type=int, default=65536)
    parser.add_argument('--limit', type=int, help='Bound pending work, preserving the full manifest.')
    args = parser.parse_args()
    if min(args.workers, args.score_workers, args.max_output_tokens) < 1 or (args.limit is not None and args.limit < 1):
        parser.error('Workers, token budget, and limit must be positive')
    if args.output is None:
        args.output = Path(__file__).resolve().parent / 'runs' / f'{args.benchmark}-initial-high-{args.scope}'
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / '.run.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error(f'Another evaluator owns {args.output}')
        rows, config = prepare(args)
        stages = ['generate', 'score', 'auxiliary'] if args.stage == 'all' else [args.stage]
        for stage in stages:
            if stage == 'generate':
                run_generation(args, rows, config, gemini_generate)
            elif stage in {'score', 'auxiliary'}:
                native_base.run_stage(args, rows, config, stage)
            elif stage == 'export-corrected':
                export_corrected(args, rows, config)
        complete = summarize(args, rows, config)
        if args.stage == 'all' and complete:
            export_corrected(args, rows, config)
    return 0 if complete or args.limit or args.stage != 'all' else 1


if __name__ == '__main__':
    raise SystemExit(main())
