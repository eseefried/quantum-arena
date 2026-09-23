"""Replay a model's already-generated T1 candidate code against QuantumBenchEval_T1_graded.json
(the corrected variant: shots/optimizer_calls scored as a closeness ratio, not exact-match gated --
see datasets/QuantumBenchEval_T1_graded.json and docs/QUANTUMBENCHEVAL.md for why). Read-only against
the model's result folder; writes <model>_t1_graded.json alongside this script.

Usage: python3 replay_t1_graded.py <model-key> <path-to-results/<model-key>>
"""
import sys, json, glob, re
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # leaderboard/ is the root; qbe/ lives directly under it
from qbe.evaluate import execute

def main(model_key, results_dir, evaluation_python):
    results_dir = Path(results_dir)
    graded_tasks = {t['task_id']: t for t in json.load(open(HERE / '..' / 'datasets' / 'QuantumBenchEval_T1_graded.json'))['tasks']}
    samples = sorted((results_dir / 'T1' / 'samples').glob('*.json'))
    rows = []
    for p in samples:
        rec = json.loads(p.read_text())
        code = (rec.get('generation') or {}).get('code')
        row = {'task_id': rec['task_id'], 'sample_index': rec['sample_index'], 'original_status': rec.get('status')}
        if code:
            task = graded_tasks[rec['task_id']]
            res = execute(code, task, 'T1', evaluation_python, 60)
            row['graded_status'] = res['status']
            m = re.search(r'QBE_METRICS:(\{.*\})', res.get('stdout', ''))
            if m:
                row['metrics'] = json.loads(m.group(1))
        rows.append(row)

    n_had_code = sum(1 for r in rows if 'graded_status' in r)
    n_passed = sum(1 for r in rows if r.get('graded_status') == 'passed')
    closenesses = [r['metrics']['resource_closeness'] for r in rows if r.get('graded_status') == 'passed' and 'metrics' in r]
    summary = {
        'model': model_key, 'samples': len(rows), 'had_generated_code': n_had_code,
        'passed_under_graded_test': n_passed,
        'pass_rate_graded': n_passed / n_had_code if n_had_code else None,
        'mean_resource_closeness_among_passing': sum(closenesses) / len(closenesses) if closenesses else None,
        'rows': rows,
    }
    out = HERE / f'{model_key}_t1_graded.json'
    out.write_text(json.dumps(summary, indent=2))
    print(f'wrote {out}')
    print(f'passed under graded test: {n_passed}/{n_had_code} ({summary["pass_rate_graded"]:.0%})' if n_had_code else 'no samples with code')

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else '.venv/bin/python')
