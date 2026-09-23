"""Derive QuantumBenchEval_T1_graded.json from the original T1 file.

Does NOT modify the original dataset. Keeps every real-correctness assertion
(cut_value, probability ranges, circuit_depth, two_qubit_gate_count, graph
structure) exactly as-is -- those still gate pass/fail. Replaces the two
undisclosed exact-match assertions (shots == N, optimizer_calls == N, where N
is an implementation detail never given to the candidate) with a symmetric
closeness ratio (min(actual, target) / max(actual, target), 0 if either side
isn't a positive number) that is reported, not gated on -- matching the
user's own example: target 100, actual 80 -> 0.80.
"""
import json
import re

SRC = '/mnt/zgx2-shared/AS-HybridQuantumBench/QuantumBenchEval_T1.json'
OUT = '/mnt/zgx2-shared/AS-HybridQuantumBench/QuantumBenchEval_T1_graded.json'

SHOTS_RE = re.compile(r"^assert results\['shots'\] == (\d+)\s*$", re.M)
CALLS_RE = re.compile(r"^assert results\['optimizer_calls'\] == (\d+)\s*$", re.M)

TEMPLATE = """\
import json as __qbe_json

def __qbe_num(value):
    # Qiskit/NumPy code commonly returns numpy scalar types (int64, float64, ...),
    # which are not JSON-serializable and are not `isinstance`-compatible with
    # Python's own int/float on every NumPy version -- go through float() instead.
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def __qbe_closeness(actual, target):
    actual = __qbe_num(actual)
    if actual is None or not (actual > 0) or not (target > 0):
        return 0.0
    return min(actual, target) / max(actual, target)

__qbe_shots_num = __qbe_num(results.get('shots'))
__qbe_calls_num = __qbe_num(results.get('optimizer_calls'))
__qbe_shots_closeness = __qbe_closeness(results.get('shots'), {shots})
__qbe_optimizer_calls_closeness = __qbe_closeness(results.get('optimizer_calls'), {calls})
print('QBE_METRICS:' + __qbe_json.dumps({{
    'shots_target': {shots}, 'shots_actual': __qbe_shots_num, 'shots_closeness': __qbe_shots_closeness,
    'optimizer_calls_target': {calls}, 'optimizer_calls_actual': __qbe_calls_num,
    'optimizer_calls_closeness': __qbe_optimizer_calls_closeness,
    'resource_closeness': (__qbe_shots_closeness + __qbe_optimizer_calls_closeness) / 2,
}}))

assert __qbe_shots_num is not None and __qbe_shots_num > 0
assert __qbe_calls_num is not None and __qbe_calls_num > 0"""


def transform(test_src):
    shots_m = SHOTS_RE.search(test_src)
    calls_m = CALLS_RE.search(test_src)
    if not shots_m or not calls_m:
        raise ValueError('Expected exactly one shots== and one optimizer_calls== assertion')
    shots, calls = shots_m.group(1), calls_m.group(1)
    replacement = TEMPLATE.format(shots=shots, calls=calls)
    out = SHOTS_RE.sub(replacement, test_src, count=1)
    out = CALLS_RE.sub('', out, count=1)
    # collapse the now-empty line left behind by removing the optimizer_calls line
    out = re.sub(r'\n\n\n+', '\n\n', out)
    return out, int(shots), int(calls)


doc = json.load(open(SRC))
report = []
for task in doc['tasks']:
    new_test, shots, calls = transform(task['test'])
    task['test'] = new_test
    report.append((task['task_id'], shots, calls))

doc['topic'] = doc['topic'] + ' [graded variant: shots/optimizer_calls reported as closeness, not exact-match gated]'
with open(OUT, 'w') as f:
    json.dump(doc, f, indent=2)
    f.write('\n')

print(f'Wrote {OUT}')
for tid, s, c in report:
    print(f'  {tid}: shots target={s}, optimizer_calls target={c}')
