#!/usr/bin/env python3
"""Export lazy-loaded inspection content for the current leaderboard.

Usage: python3 scripts/export_problem_content.py --cache-root /path/to/benchmark/cache
Cache snapshots must match every recorded sample's evaluation fields in order.
Only public code and evaluation fields are exported, never generation metadata.
"""
import argparse
import json
from pathlib import Path

import export_leaderboard as source


def task_content():
    tasks = {}
    files = {
        'QiskitHumanEval': 'dataset_qiskit_test_human_eval_categorized.json',
        'QiskitHumanEvalHard': 'dataset_qiskit_test_human_eval_hard.json',
        'QuanBench44': 'QuanBench44_categorized.jsonl',
        'QuanBench117': 'QuanBench117_categorized.jsonl',
    }
    for dataset, filename in files.items():
        path = source.BENCHMARKS_ROOT / filename
        items = source.load_jsonl(path) if path.suffix == '.jsonl' else source.load_json(path)
        tasks[dataset] = {}
        for item in items:
            prompt = item.get('complete_prompt') or item.get('prompt') or ''
            solution = item.get('canonical_solution') or ''
            if dataset == 'QiskitHumanEval' and solution:
                solution = prompt + solution
            tasks[dataset][str(item['task_id'])] = {'prompt': prompt, 'canonical_solution': solution}
    return tasks


def matching_cache(cache_root, dataset, raw_model, task_id, samples):
    if cache_root is None:
        return None
    folder = source.DATASET_CI_KEY[dataset]
    if dataset.startswith('QuanBench'):
        folder = 'quanbench'
        raw_model += '-' + dataset.removeprefix('QuanBench')
    path = cache_root / folder / raw_model / (task_id + '.json')
    # Refuse ambiguous/partial histories: snapshot order is the benchmark's order.
    if not path.is_file():
        return None
    cached = source.load_json(path)
    if not isinstance(cached, list) or len(cached) != len(samples):
        return None
    keys = ('passed', 'syntax_valid', 'runtime_error', 'process_fidelity')
    for actual, recorded in zip(cached, samples):
        if not isinstance(actual, dict) or not isinstance(recorded, dict):
            return None
        if actual.get('task_id', task_id) != task_id:
            return None
        if any(actual.get(key) != recorded[key] for key in keys if key in recorded):
            return None
        if recorded.get('code') and recorded['code'] != actual.get('generated_code', actual.get('code')):
            return None
    return cached


def export(cache_root=None):
    tasks = task_content()
    best, _ = source.collect_latest_result_files()
    rows = source.load_json(source.OUT_DIR / 'leaderboard_details.json')
    shards = {}
    matched = outputs = total = 0
    for row in rows:
        dataset, model, tid = row['dataset'], row['model'], row['task_id']
        run = best[(model, dataset)]
        samples = run[3].get(tid, [])
        if len(samples) != row['n_samples'] or sum(s.get('passed') is True for s in samples) != row['n_passed']:
            raise ValueError(f'Results differ from exported leaderboard: {dataset}/{model}/{tid}')
        cached = matching_cache(cache_root, dataset, run[2]['assistant'], tid, samples)
        matched += cached is not None
        attempts = []
        for i, sample in enumerate(samples[:5]):
            extra = cached[i] if cached else {}
            attempt = {key: sample[key] for key in ('passed', 'syntax_valid', 'runtime_error') if key in sample}
            attempt['code'] = sample.get('code') or sample.get('generated_code') or extra.get('generated_code') or extra.get('code') or ''
            logs = extra.get('error_message') or sample.get('error_message')
            tests = extra.get('test_results')
            if logs:
                attempt['logs'] = str(logs)
            elif tests:
                attempt['logs'] = json.dumps(tests, indent=2)
            outputs += bool(attempt['code'])
            total += 1
            attempts.append(attempt)
        shard = shards.setdefault(dataset, {'tasks': tasks.get(dataset, {}), 'models': {}})
        shard['models'].setdefault(model, {})[tid] = attempts
    destination = source.OUT_DIR / 'problem_content'
    destination.mkdir(exist_ok=True)
    for dataset, shard in shards.items():
        (destination / f'{dataset}.json').write_text(json.dumps(shard, ensure_ascii=False), encoding='utf-8')
    print(f'Exported {total} attempts; {outputs} have code; {matched} task caches matched.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-root', type=Path)
    args = parser.parse_args()
    export(args.cache_root)
