#!/usr/bin/env python3
"""Build the independent QBE preview; verify saved summaries without executing candidates."""
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'qbe_export'
OUT = ROOT / 'leaderboard'
TERMINAL = {'passed', 'incorrect', 'candidate_error', 'candidate_unsupported_import',
            'evaluation_crash', 'evaluation_timeout', 'empty_output', 'truncated', 'incomplete_output'}


def read(path):
    return json.loads(path.read_text())


def metrics(rows, tasks, samples=5):
    values = {}
    for k in (1, 5):
        estimates = []
        for task in tasks:
            group = [r for r in rows if r['task_id'] == task]
            # Partial tasks and infrastructure failures are never silently scored as failures.
            if len(group) != samples or any(r['status'] not in TERMINAL for r in group):
                continue
            n, c = len(group), sum(r['status'] == 'passed' for r in group)
            if n >= k:
                estimates.append(1 - math.comb(n-c, k) / math.comb(n, k) if n-c >= k else 1.0)
        values[str(k)] = sum(estimates)/len(estimates) if estimates else None
    return values


def check(actual, expected, label):
    if isinstance(actual, float) and isinstance(expected, (float, int)):
        valid = math.isclose(actual, expected, abs_tol=1e-12)
    else:
        valid = actual == expected
    if not valid:
        raise ValueError(f'{label}: records={actual!r}, summary={expected!r}')


def topic_data(model, topic):
    dataset = read(SOURCE / 'datasets' / f'QuantumBenchEval_{topic}.json')
    tasks = [t['task_id'] for t in dataset['tasks']]
    folder = model / topic
    plan = read(folder / 'plan.json') if (folder / 'plan.json').exists() else {}
    samples = plan.get('settings', {}).get('samples', 5)
    rows = [read(p) for p in sorted((folder / 'samples').glob('*.json'))]
    slots = [(r['task_id'], r['sample_index']) for r in rows]
    if len(slots) != len(set(slots)) or any(t not in tasks or i not in range(samples) for t, i in slots):
        raise ValueError(f'{topic}: duplicate or unexpected sample slots')
    counts = dict(Counter(r['status'] for r in rows))
    execution = dict(Counter(r.get('execution', {}).get('status', 'not_executed') for r in rows))
    modules = dict(Counter(r['execution']['module'] for r in rows
                           if r.get('execution', {}).get('status') == 'candidate_unsupported_import'))
    result = dict(topic=topic, title=dataset['topic'], tasks=len(tasks), samples=len(rows),
                  expected_samples=len(tasks)*samples, recorded_tasks=len({r['task_id'] for r in rows}),
                  complete_tasks=sum(sum(r['task_id'] == t for r in rows) == samples for t in tasks),
                  counts=counts, execution_status_counts=execution, unsupported_import_modules=modules,
                  identity=plan.get('model', {}).get('identity', model.name), rows=rows)
    if topic == 'T3':
        judged = [r['judge'] for r in rows if r['status'] == 'judged']
        result.update(mean_rubric_score=sum(j['total'] for j in judged)/len(judged) if judged else None,
                      rubric_maximum=sorted({j['max_total'] for j in judged}), judged_samples=len(judged),
                      judge=plan.get('config', {}).get('judge', {}))
        for j in judged:
            check(j['judge']['model'], result['judge']['model'], 'sample judge')
    else:
        result['pass_at_k'] = metrics(rows, tasks, samples)
    summary_path = folder / 'summary.json'
    result['verified'] = summary_path.exists()
    if summary_path.exists():
        summary = read(summary_path)
        for field in ('counts', 'execution_status_counts', 'unsupported_import_modules', 'expected_samples'):
            check(result[field], summary[field], f'{topic} {field}')
        for field in ('mean_rubric_score', 'rubric_maximum') if topic == 'T3' else ():
            check(result[field], summary[field], f'{topic} {field}')
        if topic != 'T3':
            for k, value in result['pass_at_k'].items():
                check(value, summary['pass_at_k'][k], f'{topic} pass@{k}')
        for row in rows:
            check(row['fingerprint'], summary['fingerprint'], f'{topic} fingerprint')
    return result


def main():
    model = SOURCE / 'results/gemini36-flash'
    topics = [topic_data(model, f'T{i}') for i in range(1,7)]
    corrected = read(SOURCE / 't1_corrected/gemini36-flash_t1_graded.json')
    original = {(r['task_id'],r['sample_index']):r['status'] for r in topics[0]['rows']}
    replay = {(r['task_id'],r['sample_index']):r['original_status'] for r in corrected['rows']}
    check(replay, original, 'corrected replay source slots and statuses')
    check(len(corrected['rows']), len(replay), 'unique corrected rows')
    check(len(replay), corrected['samples'], 'corrected sample count')
    passed = sum(r['graded_status'] == 'passed' for r in corrected['rows'])
    check(passed, corrected['passed_under_graded_test'], 'corrected passes')
    check(passed/len(replay), corrected['pass_rate_graded'], 'corrected pass rate')
    corrected['counts'] = dict(Counter(r['graded_status'] for r in corrected['rows']))
    corrected['pass_at_k'] = metrics([dict(r, status=r['graded_status']) for r in corrected['rows']], sorted({t for t,i in replay}))
    replay_by_slot = {(r['task_id'], r['sample_index']): r for r in corrected['rows']}
    for row in topics[0]['rows']:
        row['corrected_evaluation'] = replay_by_slot[(row['task_id'], row['sample_index'])]
    for data in topics:
        dataset = read(SOURCE / 'datasets' / f'QuantumBenchEval_{data["topic"]}.json')
        data['task_details'] = dataset['tasks']
        for task in data['task_details']:
            rows = [r for r in data['rows'] if r['task_id'] == task['task_id']]
            task['sample_count'] = len(rows)
            judged = [r['judge'] for r in rows if r['status'] == 'judged']
            task['mean_rubric_score'] = sum(j['total'] for j in judged)/len(judged) if judged else None
            task['judged_samples'] = len(judged)
            task['pass_at_k'] = metrics(rows, [task['task_id']]) if data['topic'] != 'T3' else None
            if data['topic'] == 'T1':
                task['corrected_pass_at_k'] = metrics([dict(r, status=r['graded_status']) for r in corrected['rows'] if r['task_id'] == task['task_id']], [task['task_id']])
    (OUT / 'quantumbencheval.json').write_text(json.dumps(dict(topics=topics, corrected=corrected)))
    # Retain old preview URLs as links into Arena, not a separate collection UI.
    for data in topics:
        name = 'quantumbencheval' + ('' if data['topic'] == 'T1' else '-'+data['topic'])
        target = './index.html?collection=qbe&topic=' + data['topic']
        (OUT / f'{name}.html').write_text(f'<!doctype html><html lang="en"><meta charset="utf-8"><title>QuantumBenchEval</title><meta http-equiv="refresh" content="0;url={target}"><a href="{target}">Open QuantumBenchEval in Arena</a></html>')
    print('Corrected T1:', corrected['pass_at_k'])


if __name__ == '__main__':
    main()
