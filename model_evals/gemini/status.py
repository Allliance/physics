"""Read live checkpoint progress without touching evaluator state or calling models."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def line_count(path):
    if not path.exists():
        return 0
    # Writers append one JSON record; ignore an unfinished last line while polling.
    return sum(1 for line in path.read_text().splitlines() if line.strip().endswith('}'))


def status(root):
    rows = []
    for benchmark in ('phybench', 'prism', 'ugphysics'):
        initial = root / benchmark / 'initial'
        manifest = read(initial / 'manifest.json', {})
        summary = read(initial / 'summary.json', {})
        rows.append({'benchmark': benchmark, 'split': 'original', 'tools': False,
                     'questions': manifest.get('problem_count', 100), 'attempts': 1,
                     'generated': line_count(initial / 'generations.jsonl'),
                     'graded': line_count(initial / 'scores.jsonl'),
                     'complete': bool(summary.get('complete')),
                     'pass@1': summary.get('initial_accuracy'),
                     'errors': line_count(initial / 'errors.jsonl')})
        corrected = root / benchmark / 'corrected'
        summary = read(corrected / 'summary.json', {})
        imported = read(initial / 'corrected-import/predictions.json', {})
        rows.append({'benchmark': benchmark, 'split': 'corrected', 'tools': False,
                     'questions': summary.get('questions', {'phybench': 88, 'prism': 74, 'ugphysics': 78}[benchmark]),
                     'attempts': 1, 'generated': len(imported),
                     'graded': len(read(corrected / 'judgments.json', {})),
                     'complete': bool(summary.get('complete')), 'pass@1': summary.get('accuracy'),
                     'errors': line_count(corrected / 'errors.jsonl')})
    plan = read(root / 'repeated/jobs.json', {})
    for name, job in plan.get('jobs', {}).items():
        output = Path(job['output'])
        summary = read(output.with_suffix('.summary.json'), {})
        generated = graded = 0
        for n in range(1, 5):
            stem = output.stem + ('' if n == 1 else f'.round{n}')
            generated += len(read(output.with_name(stem + '.json'), {}))
            graded += len(read(output.with_name(stem + '.judged.json'), {}))
        rows.append({'benchmark': job['benchmark'], 'split': job['split'], 'tools': job['use_tools'],
                     'questions': len(job['question_ids']), 'attempts': 4,
                     'generated': generated, 'graded': graded,
                     'complete': bool(summary.get('complete')),
                     'mean@4': summary.get('mean_score'), 'pass@4': summary.get('max_score')})
        if job['benchmark'] == 'hle':
            ids = set(plan['hle_corrected_ids'])
            corrected_grades = []
            corrected_generated = 0
            for n in range(1, 5):
                suffix = '' if n == 1 else f'.round{n}'
                corrected_generated += len(ids & set(read(output.with_name(output.stem + suffix + '.json'), {})))
                path = output.with_name(output.stem.replace('original', 'corrected') + suffix + '.judged.json')
                corrected_grades.append(read(path, {}))
            values = [[grade.get(qid, {}).get('judge_response', {}).get('correct')
                       for grade in corrected_grades] for qid in ids]
            complete = all(all(v in {'yes', 'no'} for v in question) for question in values)
            rows.append({'benchmark': 'hle', 'split': 'corrected', 'tools': job['use_tools'],
                         'questions': len(ids), 'attempts': 4, 'generated': corrected_generated,
                         'graded': sum(len(g) for g in corrected_grades), 'complete': complete,
                         'mean@4': sum(v == 'yes' for q in values for v in q) / (4 * len(ids)) if complete else None,
                         'pass@4': sum('yes' in q for q in values) / len(ids) if complete else None})
    return {'updated_at': datetime.now(timezone.utc).isoformat(),
            'complete': len(rows) in {12, 16} and all(row['complete'] for row in rows), 'runs': rows}


def markdown(value):
    lines = ['# Gemini 3.1 Pro evaluation progress', '', f"Updated {value['updated_at']}", '',
             '| Dataset | Split | Tools | Answers | Grades | pass@1 | mean@4 | pass@4 |',
             '|---|---|---|---:|---:|---:|---:|---:|']
    for row in value['runs']:
        total = row['questions'] * row['attempts']
        metrics = [f"{100 * row[key]:.2f}%" if row['complete'] and row.get(key) is not None else '—'
                   for key in ('pass@1', 'mean@4', 'pass@4')]
        lines.append(f"| {row['benchmark']} | {row['split']} | {'yes' if row['tools'] else 'no'} | "
                     f"{row['generated']}/{total} | {row['graded']}/{total} | " + ' | '.join(metrics) + ' |')
    lines += ['', 'Scores are published only for complete conditions. Original UGPhysics also requires its auxiliary judgments.',
              'Corrected first-three and HLE conditions reuse original answers; these are not additional independent generations.',
              'See README.md for dataset selections, judge protocols, and Gemini reasoning/tool differences.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output_dir', type=Path)
    parser.add_argument('--write', action='store_true', help='Write progress.json and progress.md in the run directory')
    parser.add_argument('--watch', action='store_true', help='Refresh every 30 seconds while the supervisor runs')
    args = parser.parse_args()
    while True:
        value = status(args.output_dir.resolve())
        if args.write or args.watch:
            for name, content in [('progress.json', json.dumps(value, indent=2)), ('progress.md', markdown(value))]:
                path = args.output_dir / name
                temporary = path.with_suffix(path.suffix + '.tmp')
                temporary.write_text(content)
                temporary.replace(path)
        if not args.watch or value['complete']:
            print(markdown(value), flush=True)
            return
        pid_path = args.output_dir / 'supervisor.pid'
        if pid_path.exists():
            process = Path('/proc') / pid_path.read_text().strip()
            try:
                state = (process / 'stat').read_text().rsplit(')', 1)[1].split()[0]
            except FileNotFoundError:
                state = 'Z'
            if state == 'Z':
                print(markdown(value), flush=True)
                return
        time.sleep(30)


if __name__ == '__main__':
    main()
