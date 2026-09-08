#!/usr/bin/env python3
"""Recompute manuscript counts from local audit and evaluation artifacts, without API calls."""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re

from sync_yale_paper import collect_results
from validate_review_coverage import validate

ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT.parent / 'yale-paper'


def main():
    sources = {}
    def read(relative):
        path = ROOT / relative
        sources[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        return json.loads(path.read_text())

    counts = collect_results(ROOT/'audit/audits_processed.csv', ROOT/'audit/initial_data/selected',
                             json.loads((PAPER/'results/audit_counts.json').read_text()))
    coverage = validate(ROOT/'audit/audits.csv', ROOT/'audit/audits_processed.csv', ROOT/'audit/audit-overrides.json')
    with (ROOT/'audit/audits_processed.csv').open(newline='') as handle:
        audits = list(csv.DictReader(handle))
    bad = {ds: {r['source_problem_id'] for r in audits if r['dataset'] == ds and r['label'] == 'PROBLEM_FAILURE'}
           for ds in ('hle-physics', 'phybench', 'prism', 'ugphysics')}
    manifest = read('audit/initial_data/selected/selection-manifest.json')
    evaluations = {}

    def repeated(path, exclusions=None):
        data = read(path)
        if not data['complete'] or data['rounds'] != 4:
            raise ValueError(f'Incomplete four-attempt evaluation: {path}')
        rows = data['per_question']
        if len(rows) != data['questions']:
            raise ValueError(f'Question count mismatch: {path}')
        for row in rows.values():
            scores = row['round_scores']
            if len(scores) != 4 or any(type(x) is not int or x not in (0, 1) for x in scores):
                raise ValueError(f'Invalid attempt scores: {path}')
            if row['mean'] != sum(scores)/4 or row['max'] != max(scores):
                raise ValueError(f'Per-question aggregate mismatch: {path}')
        total, solved = sum(sum(r['round_scores']) for r in rows.values()), sum(r['max'] for r in rows.values())
        if abs(data['mean_score'] - total/(4*len(rows))) > 1e-12 or abs(data['max_score'] - solved/len(rows)) > 1e-12:
            raise ValueError(f'Summary arithmetic mismatch: {path}')
        if exclusions is not None:
            if not exclusions <= rows.keys():
                raise ValueError(f'Missing excluded IDs: {path}')
            if set(rows) != set(manifest['benchmarks']['hle-physics']['selected_problem_ids']):
                raise ValueError(f'HLE selection mismatch: {path}')
            rows = {k: v for k, v in rows.items() if k not in exclusions}
        total, solved = sum(sum(r['round_scores']) for r in rows.values()), sum(r['max'] for r in rows.values())
        return dict(questions=len(rows), correct_attempts=total, total_attempts=4*len(rows), solved=solved,
                    mean_at_4=100*total/(4*len(rows)), pass_at_4=100*solved/len(rows),
                    model=data['model'], question_ids=sorted(rows), source=path)

    for model, folder in [('GPT-5.6-Sol High', 'gpt56sol-high-initial-20260906'), ('Fable High', 'fable5-initial-20260906')]:
        for tools in ('tools', 'no_tools'):
            path = f'benchmarks/hle/artifacts/{folder}/{tools}.summary.json'
            evaluations[f'HLE {model} {tools} initial'] = repeated(path)
            evaluations[f'HLE {model} {tools} corrected'] = repeated(path, bad['hle-physics'])
    for condition in ('tools', 'no_tools'):
        for stage, folder, stem in [('initial', 'mean-pass-at4-20260906', 'original'),
                                    ('corrected', 'clean-refresh-20260906', 'clean')]:
            path = f'analysis/CMT-Benchmark/artifacts/{folder}/{stem}_{condition}.summary.json'
            evaluations[f'CMT GPT-5.6-Sol High {condition} {stage}'] = repeated(path)
    for model, folder, stem in [('GPT-5.6-Sol Max', 'sol-max-tools-four-rounds-20260907', 'gpt-5.6-sol'),
                               ('Fable High', 'fable-high-astra-max-four-rounds-20260907', 'fable')]:
        for stage in ('original', 'corrected'):
            path = f'analysis/CritPt/artifacts/{folder}/{stem}-{stage}.summary.json'
            evaluations[f'CritPt {model} {stage}'] = repeated(path)
        before = set(evaluations[f'CritPt {model} original']['question_ids'])
        after = set(evaluations[f'CritPt {model} corrected']['question_ids'])
        if before - after != {'00'} or after - before:
            raise ValueError('Unexpected CritPt original/corrected ID difference')

    fable_initial = read('model_evals/fable/initial_results.json')
    for ds in ('phybench', 'prism', 'ugphysics'):
        data = read(f'eval/artifacts/fable-high-audit-credit/{ds}/summary.json')
        rows = data['per_question']
        ids = [r['id'] for r in rows]
        expected = set(manifest['benchmarks'][ds]['selected_problem_ids']) - bad[ds]
        if len(ids) != len(set(ids)) or set(ids) != expected or not data['complete']:
            raise ValueError(f'Fable retained coverage mismatch: {ds}')
        correct = sum(r['correct'] for r in rows)
        if correct != data['correct'] or len(rows) != data['questions'] or abs(correct/len(rows)-data['accuracy']) > 1e-12:
            raise ValueError(f'Fable aggregate mismatch: {ds}')
        initial = fable_initial[ds]
        if not initial['complete'] or initial['total'] != 100 or initial['initial_accuracy'] != initial['initial_correct']/100:
            raise ValueError(f'Fable initial summary mismatch: {ds}')
        evaluations[f'{ds} Fable High'] = dict(initial_solved=initial['initial_correct'], initial_questions=100,
            questions=len(rows), solved=correct, pass_at_1=100*correct/len(rows),
            source=f'eval/artifacts/fable-high-audit-credit/{ds}/summary.json')

    # Check every displayed accuracy pair in the live main-results table.
    table = (PAPER/'sections/results.tex').read_text().split(r'\end{table*}', 1)[0]
    actual = re.findall(r'\$([^$]+?)\s+\\rightarrow\s+([^$]+?)\$', table)
    expected_pairs = []
    by_dataset = {r['dataset']: r for r in counts['benchmarks']}
    for ds in ('phybench', 'prism', 'ugphysics'):
        f = evaluations[f'{ds} Fable High']
        expected_pairs.append((f"{f['initial_solved']:.2f}", f"{f['pass_at_1']:.2f}"))
        r = by_dataset[ds]
        expected_pairs.append((f"{100*(r['evaluated']-r['rejected'])/r['evaluated']:.2f}",
                               f"{100*(r['evaluated']-r['rejected']+r['grader'])/(r['evaluated']-r['problem']):.2f}"))
    for metric in ('mean_at_4', 'pass_at_4'):
        for model in ('Fable High', 'GPT-5.6-Sol High'):
            expected_pairs.append(tuple(f"{evaluations[f'HLE {model} tools {stage}'][metric]:.2f}"
                                        for stage in ('initial', 'corrected')))
    for metric in ('mean_at_4', 'pass_at_4'):
        expected_pairs.append(tuple(f"{evaluations[f'CMT GPT-5.6-Sol High tools {stage}'][metric]:.2f}"
                                    for stage in ('initial', 'corrected')))
    for metric in ('mean_at_4', 'pass_at_4'):
        for model in ('Fable High', 'GPT-5.6-Sol Max'):
            expected_pairs.append((r'\text{--}', f"{evaluations[f'CritPt {model} corrected'][metric]:.2f}"))
    if actual != expected_pairs:
        raise ValueError(f'Main table differs from recomputed runs: actual={actual}; expected={expected_pairs}')

    appendix = (PAPER/'sections/appendix.tex').read_text().replace(r'\_', '_')
    listed_ids = re.findall(r'\\mbox\{([^}]+)\}', appendix)
    expected_ids = manifest['benchmarks']['ugphysics']['selected_problem_ids'] + manifest['benchmarks']['prism']['selected_problem_ids']
    if listed_ids != expected_ids:
        raise ValueError('Printed sampled IDs differ from selection manifest (including order)')
    raw_groups = {}
    with (ROOT/'audit/audits.csv').open(newline='') as handle:
        for row in csv.DictReader(handle):
            raw_groups.setdefault((row['dataset'], row['source_problem_id']), []).append(row['label'])
    pairs = Counter((key[0], tuple(sorted(set(labels)))) for key, labels in raw_groups.items() if len(set(labels)) > 1)
    cmt = read('analysis/CMT-Benchmark/data/cmt_data_clean.json')
    cmt_categories = Counter((r['audit_status'],r['correction_state']) for r in cmt)
    verdicts = read('analysis/CritPt/verdicts.json')
    ledger = read('analysis/CritPt/verdict_review.json')
    report = dict(scope='Recorded audit/evaluation counts, denominators, model attribution, and sampled IDs; not independent scientific re-review or external literature verification.',
                  reviewer_coverage=coverage['summary'], reviewer_coverage_passed=coverage['passed'],
                  audit_counts=counts['benchmarks'], audit_source=counts['source'], evaluations=evaluations,
                  printed_sample_ids_match=True, main_table_accuracy_pairs_match=True,
                  original_conflict_pairs=[dict(dataset=ds, labels=list(labels), count=n) for (ds, labels),n in sorted(pairs.items())],
                  cmt_categories=[dict(status=s, state=t, count=n) for (s,t),n in sorted(cmt_categories.items())],
                  critpt_review=dict(ledger_items=len(ledger['challenges']), final_verdicts=len(verdicts),
                                    categories=dict(Counter(v['problem'] for v in verdicts.values())),
                                    missing_verdicts=sorted(set(ledger['challenges'])-set(verdicts))),
                  source_sha256=sources)
    out = ROOT/'audit/reports/paper_numbers.json'
    out.write_text(json.dumps(report,indent=2)+'\n')
    lines = ['# Paper number reconciliation', '',
             'Reviewer coverage: **FAIL — 47 singly reviewed problems lack overrides. All 56 conflicts have explicit overrides.**', '',
             'The 250 processed labels reproduce from 446 submitted reviews and 63 overrides. Exact audit IDs match all initial rejections in the selected exports.', '',
             '| Dataset | Evaluated | Audited | Problem | Grader | Model | Retained | Audit-derived solved |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    totals = Counter()
    for r in counts['benchmarks']:
        fields = ('evaluated','rejected','problem','grader','model')
        vals=[r[k] for k in fields];vals += [r['evaluated']-r['problem'],r['evaluated']-r['rejected']+r['grader']]
        lines.append('| '+r['name']+' | '+' | '.join(map(str, vals))+' |')
        totals.update({k:r[k] for k in fields})
    lines += ['', '**Totals:** 502 evaluated, 252 initially accepted, 250 rejected; 147 problem errors, 90 grading errors, 13 model errors. After exclusion: 342/355 = 96.34%. All counts are provisional pending reviewer coverage.', '',
              '## Recomputed saved evaluations', '', '| Run | Questions | Correct attempts / attempts | Solved | Score |', '|---|---:|---:|---:|---|']
    for name,r in evaluations.items():
        attempts=f"{r['correct_attempts']}/{r['total_attempts']}" if 'total_attempts' in r else 'single attempt'
        score=f"mean@4 {r['mean_at_4']:.2f}%; pass@4 {r['pass_at_4']:.2f}%" if 'mean_at_4' in r else f"pass@1 {r['pass_at_1']:.2f}%"
        lines.append(f"| {name} | {r['questions']} | {attempts} | {r['solved']} | {score} |")
    lines += ['', '## Applied corrections and remaining evidence gaps', '',
              '- Replaced stale appendix totals 132/98/20 and 508/258/376 with 147/90/13 and 502/252/355.',
              '- Removed the unsupported CritPt 55/22/22/0/0 attribution row. CritPt/CMT are outside this processed CSV.',
              '- Separated audit-derived 104/202 → 106/115 HLE estimates from later-run 113/202 → 105/115 scores. All four HLE mean/pass figures reproduce after excluding the current 87 problem-error IDs.',
              '- Corrected CritPt model attribution: 92.59% belongs to Astra (50/54); the Sol Max results used in the table are 94.44% (51/54). Corrected evaluation has 54 challenges, not 55.',
              '- The CritPt ledger covers 59 numbered challenges: 57 final verdicts, two unresolved. The 54-item evaluation omits clean challenge 38 as well as unresolved 11/54 and unrepairable 41/46. Its original-input run adds example 00; it is not an official 55-challenge score.',
              '- Omitted unverified official CritPt initial values 28.60%, 32.30%, and figure value 34.1%. Source API results, settings, and metric are required to reinstate them. Local original-input runs are reported separately, not substituted for official scores.',
              '- Restored PHYBench’s four-attempt GPT audit result as distinct from single-attempt Fable results; selected response exports alone do not establish exact original model snapshots/tool settings. Existing attribution follows manuscript and local workflow descriptions, pending original run manifests.',
              '- Preserved concurrent Fable credit-method updates (79/88, 66/74, 66/78); checked their retained IDs and per-question totals. These differ from plain rejudging (75/88, 64/74, 66/78).',
              '- Corrected sampling description to stratified deterministic selection. The UG parent export has 1,000 rows; PRISM has 833. All 200 printed UG/PRISM sampled IDs match, including order.',
              '- Removed unsupported full-dataset UG percentages and the unverified external system-card numerical comparison from the live appendix; the original text remains in Git history. This check does not verify external literature counts, physics derivations, or quoted expert notes.',
              '- Two-reviewer/override compliance for CMT and CritPt cannot be established by this CSV. Their review workflows are separate; no human review or override was fabricated.',
              '- Fixed generated audit tables/macros to use count-consistent audit fractions, and prevented audit sync from overwriting separate measured figure scores.',
              '', 'Full source hashes, per-run question IDs, and recomputed counts are in paper_numbers.json. Missing reviewer IDs are enumerated by problem in reviewer_coverage.md (reviewer identities themselves are not exported).', '']
    (ROOT/'audit/reports/paper_numbers.md').write_text('\n'.join(lines))
    # Only aggregates and provenance go into the paper repository.
    public = dict(report)
    public['evaluations'] = {k:{f:v for f,v in r.items() if f != 'question_ids'} for k,r in evaluations.items()}
    (PAPER/'reports/number_reconciliation.json').write_text(json.dumps(public,indent=2)+'\n')
    (PAPER/'reports/number_reconciliation.md').write_text('\n'.join(lines))
    print('Verified selected audit coverage, 200 printed IDs, 16 repeated-run summaries, HLE exclusions, and three Fable retained sets.')
    print('Reviewer policy: FAIL (47 missing overrides); see audit/reports/reviewer_coverage.md.')


if __name__ == '__main__':
    main()
