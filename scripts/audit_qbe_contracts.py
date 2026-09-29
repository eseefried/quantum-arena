#!/usr/bin/env python3
"""Step 1 only: audit saved contracts/tracebacks; never run model code or alter scoring."""
import ast
import collections
import csv
import hashlib
import json
import re
import warnings
from pathlib import Path
from qbe_contract_enumeration import enumerate_task

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'qbe_export'
OUT = ROOT / 'audit'


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def natural(value):
    return tuple(int(s) if s.isdigit() else s for s in re.split(r'(\d+)', str(value)))


def write_csv(name, fields, rows):
    with (OUT / name).open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def classify(task, node, optimum):
    """Contract-only rules. No model identity, verdict, or failure count is an input.

    UNDISCLOSED on a mixed assertion applies only to the named non-disclosed aspect;
    it never authorizes dropping the solution-correctness part of that assertion.
    Ambiguities are retained explicitly rather than silently counted as correctness.
    """
    text = ast.get_source_segment(task['test'], node)
    tid = task['task_id']
    n = int(tid.split('_')[1])
    if tid.startswith('t2_'):
        if isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Constant) and any(isinstance(op, ast.In) for op in node.test.ops):
            return 'SPECIFIED', 'Presence of a field explicitly listed in both required_outputs and the saved candidate-facing return interface; preserve byte-identically.'
        if 'evaluation_cost' in text:
            return 'UNDISCLOSED', 'The field is disclosed, but neither the prompt nor callable defaults fix this exact shot/evaluation count. The literal is the exhaustive enumeration count 2**num_variables; quantum/hybrid workflows are allowed. Remove only the unsupported equality, not reporting of actual cost.'
        if 'constraint_violation_rate' in text:
            return 'UNDISCLOSED', 'Reporting the sampled violation fraction is required, but the strict success threshold in this assertion is neither stated nor implied. Finding an optimal feasible selection does not constrain the fraction of other returned samples to this literal. Preserve feasibility of the selected solution.'
        if 'feasible_objective_quality' in text:
            if n == 14:
                return 'UNDISCLOSED', 'CONTRACT CONFLICT: prompt explicitly defines achieved revenue / optimal 47; disclosed resource constraints instead imply optimum 41 (enumerated). A truthful optimal answer under the stated denominator gives 41/47, not 1.0. The test silently substitutes denominator 41. Do not delete correctness or repair the public denominator without resolving this ambiguity.'
            return 'SPECIFIED', 'The requested optimum and feasible_objective_quality definition imply 1.0 for an optimal feasible solution; optimum verified from disclosed resources/constraints. Preserve byte-identically. Prompt-supplied QUBO inconsistencies, where present, are recorded separately.'
        if 'achieved_' in text:
            reason = ('This field is absent from raw required_outputs but explicitly added to every saved candidate-facing return interface. '
                      f'The tested objective {optimum["optimum"]} is derivable from disclosed resources and constraints by exhaustive enumeration. Preserve this correctness check byte-identically.')
            if n == 14:
                reason += ' CONFLICT FLAG: the prompt also calls 47 the optimum; 41 is the actual feasible maximum, so this assertion is grounded in the problem data but inconsistent with the stated ratio denominator.'
            return 'SPECIFIED', reason
        if any(name in text for name in ('total_cpu_hours', 'total_cost', 'total_output_kw', 'total_machine_hours')):
            return 'SPECIFIED', 'The field is explicitly included in the saved return interface, and the budget/demand bound is stated in the prompt and Task inputs. Keep this feasibility check byte-identically.'
        if 'len(sel)' in text:
            return 'SPECIFIED', 'Required selection cardinality follows from the stated slot count (t2_8) or the enumerated optimal allocations and capacity limits (t2_11). Keep byte-identically; the separate element-encoding constraint is not specified.'
        if n == 6:
            return 'UNDISCLOSED', 'The selected_vms field is disclosed, but the prompt gives no tie-break rule. This assertion accepts only {VM-A,VM-B,VM-E,VM-G}, while four feasible selections attain 23. Keep budget, conflict, minimum-performance, and optimal-objective correctness; do not insist on this single optimum.'
        if n == 14:
            return 'UNDISCLOSED', 'M-labels name the orders, but selected_orders has no stated element encoding (labels versus indices/bit vector). The membership expression assumes strings. Normalize identity only; retain the conflict/optimal-membership semantics, which are derivable from the prompt. Ambiguous formatting boundary flagged; no relaxation implemented.'
        return 'UNDISCLOSED', 'The selected/activated/scheduled field is explicitly disclosed, and the optimal entities/exclusions are derivable from the prompt. However, this assertion requires one-based INTEGER entity IDs; the prompt names entities (e.g. J2/T3/QC5) without specifying return encoding. Normalize representation only and retain the same optimal-selection/constraint check; do not remove correctness.'
    if 'key in result' in text:
        return 'SPECIFIED', 'All six keys in required_keys are explicitly listed in the saved candidate-facing return interface. This is one assert statement executed once per required key; preserve byte-identically.'
    if 'reproducibility' in text:
        return 'UNDISCLOSED', 'The field is required, but its scalar type, probability interpretation, and aggregation formula are not specified in the candidate-facing prompt. This chained comparison implicitly requires a scalar in [0,1]. Retain the original numeric bound when a probability can be unambiguously normalized; multi-statistic dictionaries cannot be converted by an arbitrary choice of value.'
    if 'approximation_ratio' in text:
        if n >= 15:
            return 'SPECIFIED', 'The prompt explicitly requires approximation_ratio >= 1.0 against the natural split and supplies ref_cut. The 1e-6 tolerance only accommodates rounding. Preserve byte-identically.'
        return 'UNDISCLOSED', 'AMBIGUOUS METRIC CONTRACT: optimal partitioning is requested, but the prompt does not define approximation_ratio orientation/formula or this reference-cut normalization. The test assumes reference_cut/found_cut with larger better; found_cut/optimum is another convention. Optimal-partition correctness must remain, but this literal scalar contract is not fully determined. Do not simply remove the quality check.'
    if 'balance_constraint_score' in text:
        return 'UNDISCLOSED', 'AMBIGUOUS METRIC CONTRACT: reporting balance_constraint_score is required, but no normalization or [0,1] range is stated. Absolute size imbalance and a normalized score are different reasonable reports. Keep any explicitly requested balance constraint; do not silently choose a normalization or waive partition correctness.'
    if 'modularity_score' in text:
        return 'SPECIFIED', 'The conventional modularity metric for the supplied unweighted undirected graph lies within [-1,1]; this broad mathematical range follows from the named metric. Preserve byte-identically.'
    if 'normalized_cut_score' in text:
        return 'SPECIFIED', 'A normalized cut on a graph with nonnegative unweighted edges is nonnegative. This is a mathematical validity bound, not an undisclosed optimum target; preserve byte-identically.'
    if 'runtime' in text:
        return 'SPECIFIED', 'Elapsed runtime of a nonempty computation is positive; this basic validity bound follows from reporting runtime and imposes no arbitrary budget. Preserve byte-identically.'
    raise ValueError((tid, text))


def parse_prompt(prompt):
    narrative, rest = prompt.split('\n\nTask inputs:\n', 1)
    inputs, rest = rest.split('\n\nRequired Python interface:\n', 1)
    signature, tail = rest.split('\nReturn a dictionary with these outputs: ', 1)
    outputs, environment = tail.split('\nSupported environment: ', 1)
    return dict(narrative=narrative, task_inputs=json.loads(inputs), signature=signature,
                required_outputs_candidate=outputs.split(', '), environment_and_instructions=environment,
                # Complete sentences/clauses retained, including spelled-out numbers and qualitative constraints.
                stated_requirements=re.split(r'(?<=[.!?])\s+(?=[A-Z])', narrative),
                numeric_literals_in_narrative=[dict(value=m.group(), context=narrative[max(0,m.start()-50):m.end()+70])
                                               for m in re.finditer(r'(?<![A-Za-z_])[-+]?\d+(?:\.\d+)?', narrative)])


def first_failure(record, task):
    ex = record.get('execution', {})
    tb = ex.get('traceback', '')
    frames = re.findall(r'File "([^"]+)", line (\d+)', tb)
    exceptions = re.findall(r'^([\w.]+(?:Error|Exception|Interrupt|Exit))(?::|$)', tb, re.M)
    error_type = exceptions[-1] if exceptions else ''
    failure_file, line = frames[-1] if frames else ('', '')
    dataset_frames = [int(n) for f, n in frames if f == '<dataset-test>']
    assertion_line = ''
    if failure_file == '<dataset-test>':
        line = int(line)
        for node in ast.walk(ast.parse(task['test'])):
            if isinstance(node, ast.Assert) and node.lineno <= line <= node.end_lineno:
                assertion_line = node.lineno
                break
    if record['status'] == 'passed':
        bucket = 'passed'
    elif assertion_line:
        bucket = f'{error_type or record["status"]} @ assertion L{assertion_line}'
    elif failure_file == '<dataset-test>':
        bucket = f'{error_type or record["status"]} @ non-assert test L{line}'
    else:
        bucket = record['status'] + (f' / {error_type}' if error_type else '') + ' (before assertion verdict)'
    return dict(status=record['status'], first_failure_bucket=bucket, exception=error_type,
                first_assertion_line=assertion_line, failure_file=failure_file, failure_line=line,
                dataset_call_line=dataset_frames[-1] if dataset_frames else '',
                error=ex.get('error', ''), traceback=tb)


def dict_shape(record):
    """Static evidence only, not a claim that every branch was executed."""
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', SyntaxWarning)
        try:
            tree = ast.parse(record.get('generation', {}).get('code', ''))
        except SyntaxError:
            return []
    assignments = collections.defaultdict(list)
    values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id].append(node.value)
                if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant) and target.slice.value == 'reproducibility':
                    values.append(node.value)
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == 'reproducibility':
                    values.append(value)
    result = []
    for value in values:
        resolved = assignments.get(value.id, []) if isinstance(value, ast.Name) else [value]
        dictionaries = [v for v in resolved if isinstance(v, ast.Dict)]
        result.append(dict(line=value.lineno, expression=ast.unparse(value)[:250],
                           literal_dictionary_keys=[[k.value if isinstance(k, ast.Constant) else '<computed>' for k in v.keys] for v in dictionaries]))
    return result


def main():
    OUT.mkdir(exist_ok=True)
    tasks = {}; dataset_hashes = {}
    for topic in ('T2', 'T6'):
        path = SOURCE / 'datasets' / f'QuantumBenchEval_{topic}.json'
        dataset_hashes[topic] = digest(path)
        for task in read(path)['tasks']:
            tasks[task['task_id']] = task
    models = sorted(p.name for p in (SOURCE / 'results').iterdir() if p.is_dir())
    assertions = {}; optima = {}
    # Classification happens before failure records are read.
    for tid, task in tasks.items():
        optimum = enumerate_task(task) if tid.startswith('t2_') else None
        if optimum:
            optima[tid] = optimum
        assertions[tid] = []
        for node in sorted((n for n in ast.walk(ast.parse(task['test'])) if isinstance(n, ast.Assert)), key=lambda n:n.lineno):
            classification, reason = classify(task, node, optimum)
            assertions[tid].append(dict(line=node.lineno, end_line=node.end_lineno,
                                        assertion=ast.get_source_segment(task['test'], node), classification=classification, reason=reason))
    samples = []; prompt_variants = collections.defaultdict(dict); checks = []; shapes = []
    source_manifest = {}
    for model in models:
        for topic in ('T2', 'T6'):
            folder = SOURCE / 'results' / model / topic
            plan = read(folder / 'plan.json'); summary = read(folder / 'summary.json')
            assert plan['dataset']['sha256'] == dataset_hashes[topic], (model, topic, 'dataset hash mismatch')
            records = []
            slots = set()
            for path in sorted((folder / 'samples').glob('*.json'), key=natural):
                source_manifest[str(path.relative_to(ROOT))] = digest(path)
                r = read(path); tid = r['task_id']; slot = (tid, r['sample_index'])
                assert tid in tasks and slot not in slots and 0 <= r['sample_index'] < 5
                slots.add(slot); records.append(r)
                assert r['fingerprint'] == summary['fingerprint']
                assert r['prompt'] == r['generation']['prompt']
                pr = r['prompt']; sha = hashlib.sha256(pr.encode()).hexdigest()
                variant = prompt_variants[tid].setdefault(sha, dict(prompt=pr, paths=[]))
                variant['paths'].append(str(path.relative_to(ROOT)))
                evidence = first_failure(r, tasks[tid])
                samples.append(dict(sample_id=f'{tid}.{r["sample_index"]}', model=model, topic=topic, task_id=tid,
                                    sample_index=r['sample_index'], source=str(path.relative_to(ROOT)), **evidence))
                if topic == 'T6' and evidence['exception'] == 'TypeError' and evidence['first_assertion_line']:
                    target = next(a for a in assertions[tid] if a['line'] == evidence['first_assertion_line'])
                    if 'reproducibility' in target['assertion']:
                        shapes.append(dict(model=model, sample_id=f'{tid}.{r["sample_index"]}', error=evidence['error'], source=str(path.relative_to(ROOT)), static_evidence=dict_shape(r)))
            assert dict(collections.Counter(r['status'] for r in records)) == summary['counts']
            assert len(records) == summary['expected_samples']
            expected={(tid,i) for tid in tasks if tid.startswith(topic.lower()+'_') for i in range(5)}
            assert slots == expected
            passed=sum(r['status']=='passed' for r in records)
            assert abs(passed/len(records)-summary['pass_at_k']['1']) < 1e-12
            checks.append(dict(model=model, topic=topic, samples=len(records), passed=passed, pass1=summary['pass_at_k']['1'], counts=summary['counts'], dataset_sha256=dataset_hashes[topic]))
    contracts = []
    for tid, task in tasks.items():
        assert len(prompt_variants[tid]) == 1, (tid, 'classifications require a separate review per prompt variant')
        sha, variant = next(iter(prompt_variants[tid].items()))
        parsed = parse_prompt(variant['prompt'])
        disclosed = parsed['required_outputs_candidate']
        # Guard against falsely treating augmented fields as undisclosed.
        tested = {n.slice.value for n in ast.walk(ast.parse(task['test'])) if isinstance(n, ast.Subscript)
                  and isinstance(n.value, ast.Name) and n.value.id == 'result' and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str)}
        assert tested <= set(disclosed), (tid, tested - set(disclosed))
        for key in ('resources','constraints','graph_vertices','graph_edges'):
            if key in task:
                assert parsed['task_inputs'][key] == task[key]
        contracts.append(dict(task_id=tid, required_outputs_dataset=task['required_outputs'],
                              additional_disclosed_outputs=[k for k in disclosed if k not in task['required_outputs']],
                              **parsed, saved_prompt_sha256=sha, candidate_prompt_verbatim=variant['prompt'],
                              sample_sources=variant['paths'], assertion_suite_verbatim=task['test'],
                              assertions=assertions[tid], discrete_optimum_from_disclosed_constraints=optima.get(tid)))
    rows = []
    for tid, suite in assertions.items():
        for a in suite:
            counts = {model:sum(s['model']==model and s['task_id']==tid and s['first_assertion_line']==a['line'] for s in samples) for model in models}
            rows.append(dict(task_id=tid, assertion=f'L{a["line"]}: {a["assertion"]}', classification=a['classification'], reason=a['reason'], n_samples_failing_first_here_by_model=json.dumps(counts, sort_keys=True)))
    write_csv('qbe_t2_t6_contracts.csv', ['task_id','assertion','classification','reason','n_samples_failing_first_here_by_model'], rows)
    write_csv('qbe_t2_t6_first_failures.csv', list(samples[0]), samples)
    grouped = collections.Counter((s['model'],s['task_id'],s['first_failure_bucket'],s['exception'],s['first_assertion_line']) for s in samples)
    write_csv('qbe_t2_t6_failure_counts.csv', ['model','task_id','first_failure','exception','assertion_line','count'],
              [dict(zip(['model','task_id','first_failure','exception','assertion_line','count'], [*key,value])) for key,value in sorted(grouped.items(), key=lambda x:str(x[0]))])
    (OUT / 'qbe_t2_t6_prompt_inventory.json').write_text(json.dumps(contracts, indent=2, ensure_ascii=False)+'\n')
    (OUT / 'qbe_t6_reproducibility_shapes.json').write_text(json.dumps(shapes, indent=2, ensure_ascii=False)+'\n')
    summary_rows=[]
    for tid, suite in assertions.items():
        subs=[s for s in samples if s['task_id']==tid]
        failures=collections.Counter(s['first_failure_bucket'] for s in subs if s['status']!='passed')
        assertion_failures=collections.Counter(s['first_failure_bucket'] for s in subs if s['first_assertion_line'])
        dominant = ' / '.join(f'{key}: {count}' for key,count in failures.most_common(1)) or 'None'
        dominant_assertion = ' / '.join(f'{key}: {count}' for key,count in assertion_failures.most_common(1)) or 'None'
        summary_rows.append(dict(task_id=tid, assertions=len(suite), undisclosed=sum(a['classification']=='UNDISCLOSED' for a in suite),
                                 samples=len(subs), passed=sum(s['status']=='passed' for s in subs), dominant_failure=dominant,
                                 dominant_assertion_failure=dominant_assertion))
    write_csv('qbe_t2_t6_task_summary.csv', list(summary_rows[0]), summary_rows)
    # Final source-integrity check after all writes: no original dataset, scorer, or sample is changed.
    for path in sorted((SOURCE / 'qbe').glob('*.py')):
        source_manifest[str(path.relative_to(ROOT))] = digest(path)
    for topic in ('T2','T6'):
        path=SOURCE / 'datasets' / f'QuantumBenchEval_{topic}.json'
        source_manifest[str(path.relative_to(ROOT))]=dataset_hashes[topic]
    assert all(digest(ROOT/path)==sha for path,sha in source_manifest.items())
    (OUT / 'qbe_t2_t6_audit_manifest.json').write_text(json.dumps(dict(stage='Step 1 only; no candidate code executed; no scoring changed', samples=len(samples), assertions=len(rows), model_topic_verification=checks, sha256=source_manifest),indent=2)+'\n')
    print(f'Verified {len(samples)} records, {len(rows)} assertion statements, {len(tasks)} tasks, {len(models)} models.')
    for row in summary_rows:
        print(f'{row["task_id"]:6} {row["undisclosed"]}/{row["assertions"]} undisclosed; dominant: {row["dominant_failure"]}')


if __name__ == '__main__':
    main()
