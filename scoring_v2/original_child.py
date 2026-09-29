"""Evaluation subprocess, v2. -I plus a fresh cwd is isolation, not a security sandbox.

Import failures are split into two categories that are never mixed:
  evaluation_environment_failure  a documented evaluation dependency is missing or broken (aborts the dataset)
  candidate_unsupported_import    the candidate's own code imports something outside the documented stack
                                  (unknown/fabricated module, nonexistent submodule, missing/removed symbol),
                                  or reaches a documented library's own optional-extra failure
                                  (e.g. PennyLane's qchem needing PySCF for a feature the task didn't require)
"""
import importlib
import importlib.util
import json
import os
import re
import sys
import traceback

# Documented evaluation stack: everything imported by the supplied canonical solutions and tests
# (audited 2026-09-21) that is not standard library. Also probed by the runner's preflight.
DOCUMENTED = {'numpy', 'scipy', 'networkx', 'qiskit', 'qiskit_aer', 'qiskit_algorithms', 'qiskit_optimization', 'pennylane', 'dimod', 'neal'}


def innermost_frame(exc):
    tb = exc.__traceback__
    while tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    return tb.tb_frame if tb is not None else None


def raised_by_candidate(exc):
    """True when the failing import statement is in the candidate's own source, not inside a library."""
    frame = innermost_frame(exc)
    return frame is not None and frame.f_code.co_filename == '<candidate>'


def optional_extra_of_documented_library(exc):
    """True when a DOCUMENTED library's own code raised this about ITS OWN optional extra
    (e.g. PennyLane's qchem needing PySCF for a feature the task doesn't require) -- the
    candidate reached past what the task needed, not a broken/incomplete environment.
    Conservative on purpose: requires both the failing frame to be inside a documented
    library's own package directory AND the library's own 'pip install <x>' install hint,
    so an unrelated or genuinely broken import (e.g. numpy itself failing under qiskit)
    is not misclassified the same way.
    """
    frame = innermost_frame(exc)
    if frame is None:
        return None
    filename = frame.f_code.co_filename.replace('\\', '/')
    if not any(f'/{pkg}/' in filename for pkg in DOCUMENTED):
        return None
    match = re.search(r'pip install ([\w\-]+)', str(exc), re.I)
    return match.group(1) if match else None


def classify_import(exc):
    """Return (status, import_kind, module) for an import failure raised while running candidate code."""
    name = getattr(exc, 'name', '') or ''
    top = name.split('.')[0]
    if not raised_by_candidate(exc):
        extra = optional_extra_of_documented_library(exc)
        if extra:
            return 'candidate_unsupported_import', 'documented_library_optional_extra', extra
        return 'evaluation_environment_failure', 'dependency_broken_inside_library', name
    if isinstance(exc, ModuleNotFoundError):
        if top in DOCUMENTED and importlib.util.find_spec(top) is None:
            return 'evaluation_environment_failure', 'documented_dependency_missing', name
        return 'candidate_unsupported_import', ('nonexistent_submodule' if top in DOCUMENTED else 'module_not_available'), name
    match = re.match(r"cannot import name '([^']+)' from '([^']+)'", str(exc))
    if match:
        symbol, module_name = match.groups()
        try:
            module = importlib.import_module(module_name)
        except Exception:
            return 'evaluation_environment_failure', 'module_failed_to_import', module_name
        if not hasattr(module, symbol):
            return 'candidate_unsupported_import', 'missing_symbol', f'{module_name}.{symbol}'
    return 'evaluation_environment_failure', 'unclassified_import_error', name


def numpy_json(value):
    """Convert NumPy values without accepting arbitrary objects or nonfinite numbers."""
    import numpy as np
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        converted = value.item()
        if not isinstance(converted, np.generic):
            return converted
    raise TypeError(f'Object of type {type(value).__name__} is not JSON serializable')


def write_marker(result_path, phase):
    """Record which phase is about to run, flushed to disk, so a hard crash (segfault, abort) that
    kills this process before it can write a real result still leaves evidence of what was running."""
    with open(result_path, 'w') as handle:
        json.dump({'status': 'in_progress', 'phase': phase}, handle)
        handle.flush(); os.fsync(handle.fileno())


def main():
    request = json.load(open(sys.argv[1]))
    result_path = sys.argv[2]
    namespace = {'__name__': '__candidate__'}
    result = {}
    phase = 'candidate'
    try:
        write_marker(result_path, phase)
        exec(compile(request['code'], '<candidate>', 'exec'), namespace)
        if request['topic'] == 'T3':
            output = namespace[request['task']['entry_point']]()
            output = json.loads(json.dumps(output, default=numpy_json, allow_nan=False))
            result = {'status': 'executed', 'output': output}
        else:
            phase = 'dataset_test'
            write_marker(result_path, phase)
            # The test script calls into the candidate's own functions, so a crash recorded here
            # is very often triggered by candidate code running under our harness, not our own bug.
            exec(compile(request['task']['test'], '<dataset-test>', 'exec'), namespace)
            result = {'status': 'passed'}
    except (ImportError, ModuleNotFoundError) as exc:
        if phase == 'candidate' or raised_by_candidate(exc):
            status, kind, module = classify_import(exc)
        else:  # dataset-test imports are ours, never the candidate's
            status, kind, module = 'evaluation_environment_failure', 'dataset_test_import', getattr(exc, 'name', '') or ''
        result = {'status': status, 'import_kind': kind, 'module': module, 'error': str(exc), 'phase': phase,
                  'traceback': traceback.format_exc()}
    except AssertionError as exc:
        result = {'status': 'incorrect', 'error': str(exc), 'traceback': traceback.format_exc()}
    except BaseException as exc:
        result = {'status': 'candidate_error', 'error': str(exc), 'traceback': traceback.format_exc()}
    with open(result_path, 'w') as handle:
        json.dump(result, handle, allow_nan=False)


if __name__ == '__main__':
    main()
