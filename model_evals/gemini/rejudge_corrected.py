"""Rejudge frozen corrected Gemini answers, preserving the native judge prompts."""

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'analysis/CMT-Benchmark'))
sys.path.insert(0, str(ROOT / 'analysis/CritPt/scripts'))

from eval import backends as unified
from eval.storage import atomic_json, file_hash, fingerprint, require_checkpoint
from benchmarks.hle.hle_eval import scoring as hle
from cmt_eval import scoring as cmt
from cmt_eval.dataset import load_dataset as load_cmt
from critpt_eval import backends as critpt
from critpt_eval.dataset import load_dataset as load_critpt
from utils.codex_cli import CodexLLM


def check(condition, message):
    if not condition:
        raise ValueError(message)


def validate_completion(result):
    """A recovered connection warning does not invalidate a completed turn."""
    terminal = [e for e in result.events if e.get('type') in {'turn.completed', 'turn.failed'}]
    if not terminal or terminal[-1]['type'] != 'turn.completed' or not result.text.strip():
        errors = [e for e in result.events if e.get('type') in {'error', 'turn.failed'}]
        raise ValueError(f'Judge turn did not complete: {json.dumps(errors)[-3000:]}')


def collect(source):
    """Validate every source before any judge calls; freeze exact rendered inputs."""
    hashes, records = {}, []

    def read(path):
        hashes[str(path)] = file_hash(path)
        return json.loads(path.read_text())

    def add(benchmark, number, questions, answers, predictions, old, prompt, system, schema,
            hash_function=fingerprint):
        ids = [q['id'] for q in questions]
        check(len(ids) == len(set(ids)) and set(ids) == set(old), f'{benchmark}: wrong baseline IDs')
        for q in questions:
            qid = q['id']
            prediction, baseline = predictions[qid], old[qid]
            check(baseline['prediction_sha256'] == hash_function(prediction),
                  f'{benchmark}/{number}/{qid}: baseline prediction mismatch')
            grade = baseline.get('judgment', baseline.get('judge_response'))
            check(grade['correct'] in {'yes', 'no'}, 'Incomplete baseline')
            check(baseline.get('judge_model', baseline.get('requested_model')) == 'claude-fable-5',
                  'Baseline must use Fable 5')
            if 'correct_answer' in grade:
                check(grade['correct_answer'] == answers[qid], 'Reference mismatch')
            if 'ground_truth' in baseline:
                check(baseline['ground_truth'] == answers[qid], 'Reference mismatch')
            check(not q.get('image'), 'Image judging needs an explicit image adapter')
            automatic = (prediction.get('refused') or prediction.get('limit_exhausted')
                         or prediction.get('status') == 'limit_exhausted')
            if automatic:
                check(grade['correct'] == 'no', 'Automatic failure has a positive baseline grade')
            rendered = (prompt + '\n' + json.dumps({'problem': q['question'],
                        'ground_truth': answers[qid], 'model_solution': prediction['response']},
                        ensure_ascii=False)) if benchmark == 'critpt' else prompt.format(
                            question=q['question'], correct_answer=answers[qid],
                            response=prediction['response'])
            records.append({'key': f'{benchmark}/{number}/{qid}', 'benchmark': benchmark,
                            'round': number, 'id': qid, 'prompt': rendered, 'system': system,
                            'schema': schema, 'prediction_sha256': hash_function(prediction),
                            'baseline': grade, 'automatic_failure': bool(automatic)})

    for benchmark in ('phybench', 'prism', 'ugphysics'):
        directory = source / benchmark / 'corrected'
        manifest = read(directory / 'manifest.json')
        for name in ('judge.txt', 'judge_system.txt', 'judge_schema.json'):
            check(file_hash(unified.PROMPTS / name) == manifest['prompts_sha256'][name],
                  f'{benchmark}: judge prompt changed')
        questions = read(directory / 'dataset.json')
        check([q['id'] for q in questions] == manifest['selection']['retained_ids'],
              f'{benchmark}: selection mismatch')
        add(benchmark, 1, questions, {q['id']: q['reference_answer'] for q in questions},
            read(directory / 'predictions.json'), read(directory / 'judgments.json'),
            unified.JUDGE, unified.JUDGE_SYSTEM, unified.SCHEMA)

    plan = read(source / 'repeated/jobs.json')
    for benchmark in ('hle', 'cmt', 'critpt'):
        job = plan['jobs'][f'{benchmark}-' + ('original' if benchmark == 'hle' else 'corrected') + '-no-tools']
        output = Path(job['output'])
        manifest = read(output.with_suffix('.run.json'))
        if benchmark == 'hle':
            rows = read(source / 'repeated/hle-corrected.json')
            questions = [{k: q[k] for k in ('id', 'question', 'category', 'image')} for q in rows]
            answers = {q['id']: q['answer'] for q in rows}
            check([q['id'] for q in questions] == plan['hle_corrected_ids'], 'HLE selection changed')
        else:
            path = Path(manifest['dataset'])
            hashes[str(path)] = file_hash(path)
            loaded = load_cmt(path) if benchmark == 'cmt' else load_critpt(path)
            questions, answers = loaded[:2]
            questions = [q for q in questions if q['id'] in manifest['question_ids']]
            answers = {q['id']: answers[q['id']] for q in questions}
            hash_function = cmt.fingerprint if benchmark == 'cmt' else fingerprint
            check(hash_function(questions) == manifest['questions_sha256'], f'{benchmark}: questions changed')
            check(hash_function(answers) == manifest['answers_sha256'], f'{benchmark}: answers changed')
        native = {'hle': hle, 'cmt': cmt, 'critpt': critpt}[benchmark]
        if benchmark == 'critpt':
            prompt, system, schema = native.JUDGE, native.JUDGE_SYSTEM, native.JUDGE_SCHEMA
            check(fingerprint([prompt, system, schema]) == manifest['judge_prompt_sha256'],
                  'CritPt judge prompt changed')
        else:
            prompt, system, schema = native.JUDGE_PROMPT, native.JUDGE_SYSTEM_PROMPT, native.JUDGE_SCHEMA
        for number in range(1, 5):
            suffix = '' if number == 1 else f'.round{number}'
            predictions = read(output.with_name(output.stem + suffix + '.json'))
            stem = output.stem.replace('original', 'corrected') if benchmark == 'hle' else output.stem
            baseline_path = output.with_name(stem + suffix + '.judged.json')
            if benchmark != 'critpt':
                metadata = read(baseline_path.with_suffix('.json.meta.json'))
                check(native.fingerprint([questions, answers]) == metadata['questions_and_answers_sha256'],
                      f'{benchmark}: baseline inputs changed')
                check(native.fingerprint([prompt, schema, system]) == metadata['judge_prompt_sha256'],
                      f'{benchmark}: judge prompt changed')
            add(benchmark, number, questions, answers, predictions, read(baseline_path),
                prompt, system, schema, fingerprint if benchmark == 'critpt' else native.fingerprint)
    check(len(records) == 1112, f'Expected 1112 corrected answers, found {len(records)}')
    return records, hashes


def compare(records, judgments):
    groups = defaultdict(list)
    for record in records:
        groups[record['benchmark']].append(record)
    results, disagreements = {}, []
    for benchmark, items in groups.items():
        pairs = [(r, judgments[r['key']]['judgment']) for r in items if r['key'] in judgments]
        up = down = 0
        for record, grade in pairs:
            old, new = record['baseline']['correct'], grade['correct']
            if old != new:
                up += new == 'yes'
                down += new == 'no'
                disagreements.append({k: record[k] for k in ('benchmark', 'round', 'id')} | {
                    'fable_correct': old, 'sol_correct': new,
                    'fable_reasoning': record['baseline']['reasoning'], 'sol_reasoning': grade['reasoning']})
        complete = len(pairs) == len(items)
        questions = {r['id'] for r in items}
        row = {'complete': complete, 'questions': len(questions), 'attempts': len(items),
               'judged': len(pairs), 'fable_yes_sol_no': down, 'fable_no_sol_yes': up,
               'disagreements': up + down}
        if complete:
            for name in ('fable', 'sol'):
                correct = [r for r in items if (r['baseline'] if name == 'fable'
                           else judgments[r['key']]['judgment'])['correct'] == 'yes']
                row[name] = {'correct_attempts': len(correct), 'mean': len(correct) / len(items),
                             'pass': len({r['id'] for r in correct}) / len(questions)}
            row['mean_change_pp'] = 100 * (row['sol']['mean'] - row['fable']['mean'])
            row['pass_change_pp'] = 100 * (row['sol']['pass'] - row['fable']['pass'])
        results[benchmark] = row
    return {'complete': all(r['complete'] for r in results.values()), 'results': results,
            'judged': len(judgments), 'total': len(records), 'disagreements': disagreements}


def report(output, records, judgments):
    value = compare(records, judgments)
    atomic_json(output / 'comparison.json', value)
    lines = ['# Corrected Gemini: Fable 5 High versus GPT-5.6-Sol High', '',
             'The same saved Gemini answers, corrected references, native merged judge prompts, and scoring rules are used. Judges use no tools. Successful judgments are cached; failures remain pending.', '',
             f"Completed: {value['judged']}/{value['total']} judgments.", '',
             '| Benchmark | Metric | Fable High | Sol High | Change (pp) |',
             '|---|---|---:|---:|---:|']
    for benchmark, row in value['results'].items():
        if not row['complete']:
            lines.append(f"| {benchmark} | pending {row['judged']}/{row['attempts']} | — | — | — |")
            continue
        repeated = row['attempts'] > row['questions']
        for metric, label in ([('mean', 'mean@4'), ('pass', 'pass@4')] if repeated else [('mean', 'pass@1')]):
            lines.append(f"| {benchmark} | {label} | {100*row['fable'][metric]:.2f}% | {100*row['sol'][metric]:.2f}% | {row[metric+'_change_pp']:+.2f} |")
    lines += ['', '| Benchmark | Fable yes → Sol no | Fable no → Sol yes | Disagreements |',
              '|---|---:|---:|---:|']
    for benchmark, row in value['results'].items():
        lines.append(f"| {benchmark} | {row['fable_yes_sol_no']} | {row['fable_no_sol_yes']} | {row['disagreements']}/{row['judged']} |")
    lines += ['', 'Differences measure judge sensitivity, not an independent determination of which judge is right.',
              'The Codex transport records the requested Sol model; it does not expose an independently observed model ID.',
              'See `disagreements.csv` for both judges’ reasoning and `inputs.json` for exact rendered judge inputs.', '']
    (output / 'COMPARISON.md').write_text('\n'.join(lines))
    with (output / 'disagreements.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['benchmark', 'round', 'id', 'fable_correct',
                               'sol_correct', 'fable_reasoning', 'sol_reasoning'])
        writer.writeheader()
        writer.writerows(value['disagreements'])
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'model_evals/gemini/runs/gemini31-20260908')
    parser.add_argument('--output', type=Path, default=ROOT / 'model_evals/gemini/runs/sol-rejudge-corrected-20260914')
    parser.add_argument('--stage', choices=['prepare', 'judge', 'summary'], default='judge')
    parser.add_argument('--workers', type=int, default=24)
    parser.add_argument('--limit', type=int, help='Only process this many pending judgments; retain full denominator')
    parser.add_argument('--timeout', type=float, default=1800)
    args = parser.parse_args(argv)
    check(args.workers > 0 and args.timeout > 0 and (args.limit is None or args.limit > 0), 'Invalid limits')
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        records, sources = collect(args.source.resolve())
        manifest = {'version': 1, 'judge_model': 'gpt-5.6-sol', 'judge_reasoning_effort': 'high',
                    'tools': False, 'mode': 'merged', 'source_sha256': sources,
                    'inputs_sha256': fingerprint(records), 'timeout': args.timeout,
                    'implementation_sha256': file_hash(Path(__file__)),
                    'transport_sha256': {str(p.relative_to(ROOT)): file_hash(p)
                                         for p in sorted((ROOT / 'utils/codex_cli').glob('*.py'))}}
        require_checkpoint(args.output / 'manifest.json', manifest)
        require_checkpoint(args.output / 'inputs.json', records)
        path = args.output / 'judgments.json'
        judgments = json.loads(path.read_text()) if path.exists() else {}
        by_key = {r['key']: r for r in records}
        check(set(judgments) <= set(by_key), 'Unexpected cached judgments')
        for key, grade in judgments.items():
            check(grade['input_sha256'] == fingerprint(by_key[key]), 'Cached input changed')
            (critpt.validate_judgment if by_key[key]['benchmark'] == 'critpt'
             else unified.validate_judgment)(grade['judgment'])
        report(args.output, records, judgments)
        if args.stage == 'judge':
            pending = [r for r in records if r['key'] not in judgments]
            if args.limit:
                pending = pending[:args.limit]

            def judge(record):
                if record['automatic_failure']:
                    return {'judgment': record['baseline'], 'judge_called': False,
                            'input_sha256': fingerprint(record)}
                client = CodexLLM(model='gpt-5.6-sol', model_reasoning_effort='high',
                                  timeout=args.timeout, system_prompt=record['system'],
                                  strict_no_tools=True, web_search='disabled', sandbox_mode='read-only',
                                  env_inherit='none', max_exec_retries=0, max_tool_retries=0)
                with tempfile.TemporaryDirectory(prefix='gemini-rejudge-') as directory:
                    schema = Path(directory) / 'schema.json'
                    schema.write_text(json.dumps(record['schema']))
                    result = client.complete(record['prompt'], output_schema=schema)
                validate_completion(result)
                content = json.loads(result.text)
                (critpt.validate_judgment if record['benchmark'] == 'critpt'
                 else unified.validate_judgment)(content)
                return {'judgment': content, 'requested_model': 'gpt-5.6-sol', 'actual_model': None,
                        'reasoning_effort': 'high', 'usage': result.usage, 'raw_response': result.text,
                        'events': result.events, 'judge_called': True, 'input_sha256': fingerprint(record),
                        'completed_at': datetime.now(timezone.utc).isoformat()}

            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = {pool.submit(judge, record): record['key'] for record in pending}
                for future in as_completed(futures):
                    key = futures[future]
                    try:
                        judgments[key] = future.result()
                    except Exception as exc:
                        with (args.output / 'errors.jsonl').open('a') as stream:
                            stream.write(json.dumps({'key': key, 'error': str(exc),
                                         'time': datetime.now(timezone.utc).isoformat()}) + '\n')
                        print(f'Pending {key}: {type(exc).__name__}: {str(exc)[-1200:]}', flush=True)
                        continue
                    atomic_json(path, judgments)
                    report(args.output, records, judgments)
                    print(f"Judged {len(judgments)}/{len(records)}: {key} = {judgments[key]['judgment']['correct']}", flush=True)
        check(all(file_hash(Path(p)) == digest for p, digest in sources.items()), 'Source changed during run')
        value = report(args.output, records, judgments)
        print(json.dumps({k: v for k, v in value.items() if k != 'disagreements'}, indent=2), flush=True)
        return 0 if value['complete'] or args.stage == 'prepare' else 2


if __name__ == '__main__':
    raise SystemExit(main())
