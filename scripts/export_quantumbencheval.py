#!/usr/bin/env python3
"""Build the independent QBE preview; verify saved summaries without executing candidates."""
import hashlib
import json
import math
import random
from collections import Counter
from pathlib import Path

from export_leaderboard import clean_model_name

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'qbe_export'
OUT = ROOT / 'leaderboard'
REPLICATES, SEED = 10000, 20260922
TERMINAL = {'passed', 'incorrect', 'candidate_error', 'candidate_unsupported_import',
            'evaluation_crash', 'evaluation_timeout', 'empty_output', 'truncated', 'incomplete_output'}


def read(path):
    return json.loads(path.read_text())


def metrics(rows, tasks, samples=5):
    values = {}
    for k in (1, 3, 5):
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


def reasoning_label(recorded):
    """Short reasoning level for the display name; None when nothing was configured."""
    recorded = (recorded or '').lower()
    if 'adaptive' in recorded:
        return 'adaptive'
    if recorded.startswith('provider default'):
        return 'default'
    if not recorded or recorded == 'not explicitly configured':
        return None
    return recorded


def quantile(sorted_values, q):
    # Linear interpolation, matching numpy.quantile's default.
    pos = q * (len(sorted_values) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def bootstrap_ci(pairs, key):
    """Percentile 95% task bootstrap of sum(num)/sum(den) over (num, den) task pairs, as the Arena CIs."""
    pairs = [p for p in pairs if p[1]]
    if len(pairs) < 2:
        return None
    rng = random.Random(int.from_bytes(hashlib.sha256((str(SEED) + repr(key)).encode()).digest()[:8], 'big'))
    n, draws = len(pairs), []
    for _ in range(REPLICATES):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        draws.append(sum(p[0] for p in sample) / sum(p[1] for p in sample))
    draws.sort()
    return [quantile(draws, .025), quantile(draws, .975)]


def pass_ci(task_metrics, key):
    return {k: bootstrap_ci([(m[k], 1) for m in task_metrics if m and m[k] is not None], (*key, k)) for k in ('1', '3', '5')}


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
    # Arena display name plus the recorded reasoning level, e.g. "GPT-6 Astra (high)".
    reasoning = reasoning_label(plan.get('settings', {}).get('reasoning'))
    result['name'] = clean_model_name(result['identity']) + (f' ({reasoning})' if reasoning else '')
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
            # Saved summaries predate pass@3, so only the k values they record are verified.
            for k, value in summary['pass_at_k'].items():
                check(result['pass_at_k'][k], value, f'{topic} pass@{k}')
        for row in rows:
            check(row['fingerprint'], summary['fingerprint'], f'{topic} fingerprint')
    return result


def build_model(model):
    topics = [topic_data(model, f'T{i}') for i in range(1,7)]
    for topic in topics:
        if not topic['verified'] and not topic['samples']:
            topic['identity'] = topics[0]['identity']
            topic['name'] = topics[0]['name']
            topic['unavailable_reason'] = 'Not completed; partial records excluded from scoring.'
    corrected = read(SOURCE / 't1_corrected' / f'{model.name}_t1_graded.json')
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
    for data in topics:
        if data['topic'] == 'T3':
            data['ci'] = bootstrap_ci([(t['mean_rubric_score'] * t['judged_samples'], t['judged_samples'])
                                       for t in data['task_details'] if t['judged_samples']], (model.name, 'T3'))
        else:
            data['ci'] = pass_ci([t['pass_at_k'] for t in data['task_details']], (model.name, data['topic']))
    corrected['ci'] = pass_ci([t['corrected_pass_at_k'] for t in topics[0]['task_details']], (model.name, 'T1', 'corrected'))
    return dict(key=model.name, topics=topics, corrected=corrected)


# The judge request repeats the prompt and code already shown; API bookkeeping is not displayed.
JUDGE_OMIT = {'request_prompt', 'usage', 'response_id'}
TASK_STATS = ('task_id', 'sample_count', 'mean_rubric_score', 'judged_samples', 'pass_at_k', 'corrected_pass_at_k')


def attempt(row):
    """Only the fields the inspection panel shows; the model output is stored once."""
    corrected = row.get('corrected_evaluation')
    return dict(sample_index=row['sample_index'], status=row['status'], prompt=row.get('prompt'),
                code=row.get('generation', {}).get('code') or row.get('completion', {}).get('raw_text'),
                execution=row.get('execution'),
                judge=row.get('judge') and {k: v for k, v in row['judge'].items() if k not in JUDGE_OMIT},
                corrected_evaluation=corrected and {k: corrected.get(k) for k in ('graded_status', 'metrics')})



def by_task(rows):
    grouped = {}
    for row in sorted(rows, key=lambda r: r['sample_index']):
        grouped.setdefault(row['task_id'], []).append(attempt(row))
    return grouped


def main():
    models = [build_model(p) for p in sorted((SOURCE / 'results').iterdir())
              if p.is_dir() and (p / 'T1').exists()]
    OUT.mkdir(parents=True, exist_ok=True)
    # Like the Arena datasets: a small score file loads up front and the prompts, solutions and
    # model outputs for a topic load only when one of its problem cells is inspected.
    content_dir = OUT / 'qbe_content'
    content_dir.mkdir(exist_ok=True)
    for index, topic in enumerate(f'T{i}' for i in range(1, 7)):
        content = dict(tasks={t['task_id']: dict(prompt=t.get('prompt'), canonical_solution=t.get('canonical_solution'))
                              for t in models[0]['topics'][index]['task_details']},
                       models={m['key']: by_task(m['topics'][index]['rows']) for m in models})
        (content_dir / f'{topic}.json').write_text(json.dumps(content))
    for m in models:
        for data in m['topics']:
            del data['rows']
            data['task_details'] = [{k: t.get(k) for k in TASK_STATS} for t in data['task_details']]
        del m['corrected']['rows']
    (OUT / 'quantumbencheval.json').write_text(json.dumps(dict(models=models)))
    print(f"Exported {len(models)} models, {sum(len(m['topics']) for m in models)} topic rows")


if __name__ == '__main__':
    main()
