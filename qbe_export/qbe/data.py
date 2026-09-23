"""Load only the supplied T1–T6 data; keep answers out of candidate prompts."""
import ast
import hashlib
import json
import re
from pathlib import Path


def digest(value):
    data = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, default=str).encode()
    return hashlib.sha256(data).hexdigest()


def load_dataset(directory, topic):
    if topic not in {f'T{i}' for i in range(1, 7)}:
        raise ValueError(f'Unknown dataset: {topic}')
    path = Path(directory) / f'QuantumBenchEval_{topic}.json'
    raw = path.read_bytes()
    document = json.loads(raw)
    tasks = document['tasks']
    seen = set()
    for task in tasks:
        for key in ('task_id', 'prompt', 'entry_point', 'test', 'required_outputs'):
            if key not in task:
                raise ValueError(f'{path}: missing {key}')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', task['task_id']):
            raise ValueError('Unsafe task ID')
        if task['task_id'] in seen:
            raise ValueError(f'Duplicate task: {task["task_id"]}')
        seen.add(task['task_id'])
        if topic == 'T3':
            rubric = json.loads(task['test'])
            if rubric.get('evaluation_mode') != 'ai_assistance':
                raise ValueError('T3 requires an AI-assistance rubric')
        else:
            tree = ast.parse(task['test'])
            if not any(isinstance(n, ast.Assert) for n in ast.walk(tree)):
                raise ValueError(f'{task["task_id"]}: no assertions')
    return tasks, {'path': str(path.resolve()), 'sha256': digest(raw),
                   'topic': document['topic'], 'task_count': len(tasks)}


def signature(task):
    """Expose the callable interface, never the canonical body or test assertions."""
    source = task.get('canonical_solution')
    if isinstance(source, str):
        for node in ast.parse(source).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == task['entry_point']:
                return f'def {node.name}({ast.unparse(node.args)}):'
    return f'def {task["entry_point"]}():'


def output_keys(task):
    """Expose the tested return interface, never expected values or assertions."""
    keys = list(task['required_outputs'])
    if task['task_id'].startswith('t3_'):
        return keys
    tree = ast.parse(task['test'])
    results = {node.targets[0].id for node in ast.walk(tree)
               if isinstance(node, ast.Assign) and len(node.targets) == 1
               and isinstance(node.targets[0], ast.Name)
               and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
               and node.value.func.id == task['entry_point']}
    tested = {node.slice.value for node in ast.walk(tree)
              if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
              and node.value.id in results and isinstance(node.slice, ast.Constant)
              and isinstance(node.slice.value, str)}
    return keys + sorted(tested - set(keys))


def candidate_prompt(task):
    # Explicit allowlist: reference answers, canonical_solution, and tests are absent.
    fields = ('physical_system', 'scientific_information', 'num_spins', 'hamiltonian',
              'parameter_sweep', 'observables_provided', 'noise_model', 'dissipation_rate',
              'graph_vertices', 'graph_edges', 'resources', 'constraints', 'num_variables',
              'coordinates_um', 'coordinates_m', 'coordinates_km', 'blockade_radius_um',
              'communication_radius_m', 'graph_coordinates_km', 'connection_radius_km',
              'graph_coordinates_m', 'chip_layout', 'layer_assignment', 'task_affinity_matrix',
              'affinity_threshold', 'same_stage_radius_m', 'cross_stage_radius_m')
    inputs = {k: task[k] for k in fields if k in task}
    # T3's reference energy is marked private by its judge template. Keep physical
    # Hamiltonian and other task inputs, but remove explicit reference-value fields.
    def redact(value):
        if isinstance(value, dict):
            return {k: redact(v) for k, v in value.items()
                    if not any(s in k.lower() for s in ('reference', 'ground_truth', 'canonical'))}
        if isinstance(value, list):
            return [redact(v) for v in value]
        return value
    inputs = redact(inputs)
    return (task['prompt'] + '\n\nTask inputs:\n' + json.dumps(inputs, indent=2, ensure_ascii=False) +
            '\n\nRequired Python interface:\n' + signature(task) +
            '\nReturn a dictionary with these outputs: ' + ', '.join(output_keys(task)) +
            '\nSupported environment: Python 3.12; Qiskit 1.4.5, qiskit-aer 0.17.2, '
            'qiskit-algorithms 0.3.1, qiskit-optimization 0.6.1, PennyLane 0.45.1, '
            'NumPy, SciPy, NetworkX, dimod and neal (dwave-neal). '
            'Use qiskit_aer for Aer, qiskit_algorithms for algorithms, and '
            'QuantumCircuit.assign_parameters for parameter binding. '
            'qiskit.Aer, BasicAer, execute, aqua, and bind_parameters are unavailable. '
            '\nInclude imports and helper functions. Do not execute at import time. '
            'Put scientific explanations in code comments/docstrings. Return only Python code.')
