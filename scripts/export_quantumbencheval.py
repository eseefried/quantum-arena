#!/usr/bin/env python3
"""Build the independent QBE preview; verify saved summaries without executing candidates."""
import json
import math
from collections import Counter
from html import escape
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


def e(value):
    return escape(str(value))


def percent(value):
    return 'Unavailable' if value is None else f'{value * 100:.2f}%'


def histogram(title, counts):
    return f'<h3>{title}</h3><dl class="qbe-statuses">' + ''.join(
        f'<div><dt>{e(k)}</dt><dd>{v}</dd></div>' for k, v in sorted(counts.items())) + '</dl>'


def render(data, corrected=None):
    topic = data['topic']
    coverage = f"{data['recorded_tasks']}/{data['tasks']} tasks · {data['samples']}/{data['expected_samples']} sample records"
    body = f'<h2>{e(data["title"])}</h2><p><strong>Gemini 3.6 Flash</strong> <span class="muted">{e(data["identity"])}</span></p><p>{coverage}</p>'
    body += f'<p>{data["complete_tasks"]}/{data["tasks"]} tasks have all requested sample slots. ' + ('Complete recorded coverage.' if data['samples'] == data['expected_samples'] else '<strong>Incomplete recorded coverage.</strong>') + '</p>'
    if topic == 'T1':
        body += '<p class="qbe-notice"><strong>Original T1 · known test limitation.</strong> Tests require exact <code>shots</code> and <code>optimizer_calls</code> values that were not disclosed to candidates. These checks can reject otherwise correct Max-Cut answers and depress the original scores.</p>'
    if topic == 'T3':
        mean = data['mean_rubric_score']
        body += f'<div class="qbe-metrics"><div><span>Mean rubric score</span><strong>{"Unavailable" if mean is None else f"{mean:.4f}"}</strong></div><div><span>Scale</span><strong>0–{e(" / ".join(map(str, data["rubric_maximum"])))}</strong></div></div>'
        body += f'<p>Judge: <strong>{e(data["judge"].get("model", "Unknown"))}</strong> · {e(data["judge"].get("protocol", ""))}</p><p class="qbe-notice"><strong>{"Incomplete rubric coverage" if data["judged_samples"] < data["expected_samples"] else "Complete rubric coverage"}: {data["judged_samples"]}/{data["expected_samples"]} samples scored.</strong> The mean includes judged samples only; unjudged samples are excluded, not assigned zero. “Judged” is a rubric status, never a pass. Execution outcomes remain separate. Energy accuracy is checked deterministically against executed output.</p>'
    else:
        body += '<div class="qbe-metrics">' + ''.join(f'<div><span>Pass@{k}</span><strong>{percent(v)}</strong></div>' for k,v in data['pass_at_k'].items()) + '</div>'
        body += '<p class="footnote">Task-averaged pass@k: 1 − C(n − c, k) / C(n, k). Only fully recorded, scorable tasks contribute. Candidate failures and truncated/empty/incomplete outputs count as unsuccessful; infrastructure failures remain unscored.</p>'
    body += histogram('Sample statuses', data['counts']) + histogram('Execution outcomes', data['execution_status_counts'])
    if data['unsupported_import_modules']:
        body += histogram('Unsupported imports', data['unsupported_import_modules'])
    if corrected:
        body += '<section class="qbe-variant"><h3>Corrected T1 · separate scoring variant</h3><p>Replay of the same 85 generated candidates, with no regeneration. Replaces only the undisclosed shots/optimizer_calls assertions with non-gating closeness ratios; retains the other correctness checks.</p>'
        body += '<div class="qbe-metrics">' + ''.join(f'<div><span>Corrected pass@{k}</span><strong>{percent(v)}</strong></div>' for k,v in corrected['pass_at_k'].items()) + '</div>'
        body += f'<p>{corrected["passed_under_graded_test"]}/{corrected["samples"]} samples passed · 17/17 tasks replayed. Verified against all saved replay rows; original statuses retained below.</p>' + histogram('Corrected replay statuses', corrected['counts']) + '</section>'
    body += '<details><summary>Inspect sample records and task coverage</summary><div class="table-scroll"><table class="board"><thead><tr><th>Task / sample</th><th>Status</th><th>Execution</th><th>Rubric score / scale</th>' + ('<th>Corrected T1 status</th>' if corrected else '') + '</tr></thead><tbody>'
    replay = {(r['task_id'],r['sample_index']):r['graded_status'] for r in corrected['rows']} if corrected else {}
    for r in data['rows']:
        j = r.get('judge', {})
        score = f'{j["total"]} / {j["max_total"]}' if r['status'] == 'judged' else '—'
        body += f'<tr><td>{e(r["task_id"])} / {r["sample_index"]}</td><td>{e(r["status"])}</td><td>{e(r.get("execution", {}).get("status", "not_executed"))}</td><td>{score}</td>' + (f'<td>{e(replay.get((r["task_id"],r["sample_index"]), "Missing"))}</td>' if corrected else '') + '</tr>'
    body += '</tbody></table></div></details><p class="footnote">' + ('Summary verified against every saved sample record.' if data['verified'] else 'No saved summary available; metrics derived from available records.') + ' Source: qbe_export/results/gemini36-flash/' + topic + '.</p>'
    template = (OUT / 'index.html').read_text().split('<header class="page-header">')[0]
    template = template.replace('<title>Quantum Arena</title>', '<title>QuantumBenchEval · Preview</title>').replace('site-nav-link active', 'site-nav-link')
    nav = '<section class="controls"><div class="control-group"><span class="control-label">Topic</span><nav class="segmented qbe-topics" aria-label="QuantumBenchEval topics">' + ''.join(f'<a href="./quantumbencheval{ "" if i == 1 else "-T"+str(i)}.html" {"aria-current=page" if topic == "T"+str(i) else ""}>T{i}</a>' for i in range(1,7)) + '</nav></div></section>'
    return template + '<header class="page-header"><h1>QuantumBenchEval <span class="qbe-badge">Preview</span></h1><p class="subtitle">A separate collection · six topics · one available model</p></header><main><p>96 tasks · 480 requested samples · five samples per task. This preview reports one model without comparative rankings or an aggregate score. The original Arena collection remains separate.</p>' + nav + '<section class="qbe-panel">' + body + '</section></main></body></html>'


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
    for data in topics:
        name = 'quantumbencheval' + ('' if data['topic'] == 'T1' else '-'+data['topic'])
        (OUT / f'{name}.html').write_text(render(data, corrected if data['topic'] == 'T1' else None))
        print(data['topic'], data.get('pass_at_k', data.get('mean_rubric_score')), data['counts'])
    print('Corrected T1:', corrected['pass_at_k'])


if __name__ == '__main__':
    main()
