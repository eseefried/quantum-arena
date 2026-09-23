"""Evaluation subprocess. -I plus a fresh cwd is isolation, not a security sandbox."""
import json
import importlib
import re
import sys
import traceback


def main():
    request = json.load(open(sys.argv[1]))
    namespace = {'__name__': '__candidate__'}
    result = {}
    phase = 'candidate'
    try:
        exec(compile(request['code'], '<candidate>', 'exec'), namespace)
        if request['topic'] == 'T3':
            output = namespace[request['task']['entry_point']]()
            json.dumps(output, allow_nan=False)
            result = {'status': 'executed', 'output': output}
        else:
            phase = 'dataset_test'
            exec(compile(request['task']['test'], '<dataset-test>', 'exec'), namespace)
            result = {'status': 'passed'}
    except (ImportError, ModuleNotFoundError) as exc:
        # These removed Qiskit APIs are candidate mistakes in the pinned environment.
        # Unknown imports and dataset-test import failures remain infrastructure errors.
        name = getattr(exc, 'name', '') or ''
        obsolete = name == 'qiskit.aqua' or name.startswith('qiskit.aqua.') or (
            name == 'qiskit' and any("cannot import name '" + symbol + "'" in str(exc)
                                     for symbol in ('BasicAer', 'Aer', 'execute')))
        missing_symbol = False
        match = re.match(r"cannot import name '([^']+)' from '([^']+)'", str(exc))
        if phase == 'candidate' and match:
            symbol, module_name = match.groups()
            try:
                module = importlib.import_module(module_name)
                missing_symbol = not hasattr(module, symbol)
            except Exception:
                pass  # A module that cannot itself import remains an environment failure.
        status = 'candidate_error' if phase == 'candidate' and (obsolete or missing_symbol) else 'evaluation_environment_failure'
        result = {'status': status, 'error': str(exc), 'phase': phase, 'traceback': traceback.format_exc()}
    except AssertionError as exc:
        result = {'status': 'incorrect', 'error': str(exc), 'traceback': traceback.format_exc()}
    except BaseException as exc:
        result = {'status': 'candidate_error', 'error': str(exc), 'traceback': traceback.format_exc()}
    with open(sys.argv[2], 'w') as handle:
        json.dump(result, handle, allow_nan=False)


if __name__ == '__main__':
    main()
