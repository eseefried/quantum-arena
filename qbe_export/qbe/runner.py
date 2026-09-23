"""Model-major, resumable QuantumBenchEval orchestration. Standard-library CLI."""
import argparse
from collections import Counter
from dataclasses import asdict
import fcntl
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import shlex
import signal
import subprocess
import sys
import time
from qbe.data import candidate_prompt, digest, load_dataset
from qbe.evaluate import execute, judge_t3

ROOT = Path(__file__).resolve().parent.parent
TERMINAL = {'passed', 'incorrect', 'candidate_error', 'evaluation_timeout', 'judged', 'empty_output', 'truncated', 'incomplete_output',
            'candidate_unsupported_import', 'evaluation_crash'}


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w') as handle:
        json.dump(value, handle, indent=2, default=str, allow_nan=False)
        handle.flush(); os.fsync(handle.fileno())
    temporary.replace(path)


def environment():
    return {'python': sys.version, 'executable': sys.executable, 'platform': platform.platform(),
            'packages': dict(sorted((d.metadata['Name'], d.version) for d in importlib.metadata.distributions()))}


def source_hashes():
    paths = list((ROOT / 'qbe').glob('*.py')) + list((ROOT / 'assistants').glob('*.py'))
    return {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sorted(paths)}


def load_config(path):
    config = json.loads(Path(path).read_text())
    registry = json.loads((ROOT / config['registry']).read_text())
    return config, {m['key']: m for m in registry['models']}


def select(requested, defaults, available):
    keys = defaults if not requested or requested == ['all'] else requested
    if len(keys) != len(set(keys)) or any(k not in available for k in keys):
        raise ValueError(f'Unknown or duplicate selection: {keys}; valid keys: {list(available)}')
    return keys


def effective(model, config, args):
    old = model['current_effective_settings']
    max_tokens = config.get('max_tokens_overrides', {}).get(model['key'], config['max_tokens'])
    reasoning = old['reasoning']
    if model['assistant_implementation'].endswith('.OpenAIGPTAssistant'):
        reasoning = os.getenv('OPENAI_REASONING_EFFORT', 'high')
        if reasoning not in {'low', 'medium', 'high', 'xhigh', 'max'}:
            raise ValueError('Invalid OPENAI_REASONING_EFFORT')
    return {'samples': 1 if args.smoke else config['samples'], 'max_tokens': max_tokens,
            'temperature': config['temperature'], 'top_p': old['top_p'] if isinstance(old['top_p'], (int, float)) else 1.0,
            'effective_api_temperature': old['temperature'] if old['temperature'] == 'not sent' else config['temperature'],
            'effective_top_p': old['top_p'], 'reasoning': reasoning,
            'precision': old['precision'], 'quantization': old['quantization']}


def blockers(model, config):
    errors = []
    key = model['key']
    for field in ('held_models', 'identity_blocks'):
        if key in config[field]: errors.append(config[field][key])
    if key not in config['selected_models']:
        errors.append('Not in selected_models; add it to the executable configuration to run')
    if 'hf_checkpoint' in model and not re.fullmatch(r'[a-fA-F0-9]{40}', config['revision_pins'].get(key, '')):
        errors.append('Missing immutable HF revision; run --resolve-revisions or supply a recorded commit')
    return errors


def probe(python, gpu=False, evaluation=False):
    script = 'import json,sys,importlib.metadata as m; print(json.dumps({"python":sys.version,"executable":sys.executable,"packages":dict(sorted((d.metadata["Name"],d.version) for d in m.distributions()))}))'
    if gpu:
        script += '; import torch; assert torch.cuda.is_available(), "CUDA unavailable"; x=torch.ones((16,16),device="cuda",dtype=torch.bfloat16); y=x@x; torch.cuda.synchronize(); assert y[0,0].item()==16; print(torch.cuda.get_device_name())'
    if evaluation:
        script += '; import numpy,scipy,networkx,qiskit,qiskit_aer,qiskit_algorithms,qiskit_optimization,pennylane,dimod,neal; from qiskit.primitives import Sampler'
    result = subprocess.run([str(python), '-c', script], capture_output=True, text=True, timeout=120)
    if result.returncode: raise RuntimeError(result.stderr[-5000:])
    return {'environment': json.loads(result.stdout.splitlines()[0]), 'details': result.stdout.splitlines()[1:]}


def worker(plan_path):
    plan = json.loads(Path(plan_path).read_text())
    output = Path(plan['output'])
    os.environ.update(CUDA_VISIBLE_DEVICES=plan.get('cuda_visible_devices', '0'),
                      HF_HOME=plan['cache'], HF_HUB_CACHE=str(Path(plan['cache']) / 'hub'),
                      XDG_CACHE_HOME=str(Path(plan['cache']) / 'xdg'))
    config, model, settings = plan['config'], plan['model'], plan['settings']
    tasks, data = load_dataset(plan['data_dir'], plan['topic'])
    if plan['smoke']: tasks = tasks[:1]
    runtime = {'plan': plan, 'environment': environment(), 'source_hashes': source_hashes(),
               'evaluation_environment': probe(plan['evaluation_python'], evaluation=True), 'dataset': data,
               'azure': {'endpoint': os.getenv('AZURE_OPENAI_ENDPOINT'), 'api_version': os.getenv('AZURE_OPENAI_API_VERSION', '2024-12-01-preview')} if model.get('identity') == 'gpt-5' else None}
    fingerprint = digest(runtime)
    provenance = output / 'provenance.json'
    if provenance.exists() and json.loads(provenance.read_text())['fingerprint'] != fingerprint:
        raise RuntimeError('Resume refused: provenance changed; use a new run ID')
    save(provenance, {'fingerprint': fingerprint, **runtime})
    records = output / 'samples'; records.mkdir(exist_ok=True)
    from qbe.models import create, classify
    assistant = tracking = None
    counts = Counter()
    for number, task in enumerate(tasks, 1):
        for index in range(settings['samples']):
            print(f'[{plan["topic"]} {number}/{len(tasks)}] {task["task_id"]} sample {index + 1}/{settings["samples"]}', flush=True)
            path = records / f'{task["task_id"]}.{index}.json'
            rec = json.loads(path.read_text()) if path.exists() else {'task_id': task['task_id'], 'sample_index': index, 'fingerprint': fingerprint}
            if rec['fingerprint'] != fingerprint: raise RuntimeError('Sample fingerprint mismatch')
            if rec.get('status') in TERMINAL:
                counts[rec['status']] += 1; continue
            if not rec.get('generation'):
                if assistant is None:
                    assistant, tracking = create(model, settings, config, Path(plan['cache']))
                    if 'hf_checkpoint' in model:
                        save(output / 'loaded_model.json', {'identity': model['identity'], 'revision': config['revision_pins'][model['key']],
                             'model_config': assistant.model.config.to_dict(), 'generation_config': assistant.model.generation_config.to_dict()})
                tracking.clear()
                prompt = candidate_prompt(task)
                generated = assistant.generate_code(prompt, num_samples=1, temperature=settings['temperature'])
                if len(generated) != 1: raise RuntimeError('Adapter must return exactly one sample')
                generation = generated[0]
                status = classify(generation, tracking)
                rec.update(status=status, generation=asdict(generation), completion=dict(tracking), prompt=prompt)
                if status == 'generation_failure':
                    rec['status'] = 'local_generation_failure' if 'hf_checkpoint' in model else 'api_failure'
                    rec['failed_generation'] = rec.pop('generation'); save(path, rec)
                    raise RuntimeError(generation.error_message or 'Generation API/model failure')
                save(path, rec)
                if status in TERMINAL:
                    counts[status] += 1; continue
            if 'execution' not in rec or rec['execution']['status'] == 'evaluation_environment_failure':
                rec['execution'] = execute(rec['generation']['code'], task, plan['topic'], plan['evaluation_python'], config['timeouts'][plan['topic']])
                rec['status'] = 'pending_judge' if plan['topic'] == 'T3' else rec['execution']['status']
                save(path, rec)
            if rec['execution']['status'] == 'evaluation_environment_failure':
                raise RuntimeError(f'Evaluation environment failure: {task["task_id"]}; see sample record')
            if plan['topic'] == 'T3':
                try:
                    rec['judge'] = judge_t3(task, rec['generation']['code'], rec['execution'], config['judge'])
                    rec['status'] = 'judged'
                except Exception as exc:
                    rec['status'] = 'judge_failure'; rec['judge_error'] = str(exc); save(path, rec)
                    raise
            save(path, rec); counts[rec['status']] += 1
    summary = {'status': 'completed', 'counts': dict(counts), 'expected_samples': len(tasks)*settings['samples'], 'fingerprint': fingerprint}
    # Execution outcomes kept apart from the scoring status (T3 records are all 'judged'), so candidate
    # import failures and environment failures are never merged. Environment failures abort before this point.
    executions = [json.loads(p.read_text()).get('execution') or {} for p in records.glob('*.json')]
    summary['execution_status_counts'] = dict(Counter(e.get('status', 'not_executed') for e in executions))
    summary['unsupported_import_modules'] = dict(Counter(e['module'] for e in executions if e.get('status') == 'candidate_unsupported_import'))
    if plan['topic'] == 'T3':
        rows = [json.loads(p.read_text()) for p in records.glob('*.json')]
        judged = [r['judge'] for r in rows if r.get('status') == 'judged']
        summary['mean_rubric_score'] = sum(r['total'] for r in judged)/len(judged) if judged else None
        summary['rubric_maximum'] = sorted({r['max_total'] for r in judged})
    if plan['topic'] != 'T3':
        values = [json.loads(p.read_text()) for p in records.glob('*.json')]
        summary['pass_at_k'] = {}
        for k in sorted({1, settings['samples']}):
            estimates = []
            for task in tasks:
                rows = [r for r in values if r['task_id'] == task['task_id']]
                n = len(rows); c = sum(r['status'] == 'passed' for r in rows)
                if n >= k:
                    estimates.append(1.0 if n-c < k else 1.0-math.comb(n-c,k)/math.comb(n,k))
            summary['pass_at_k'][str(k)] = sum(estimates)/len(estimates) if estimates else None
        summary['denominator_policy'] = 'All completed requested sample slots; empty/truncated/incomplete count as unsuccessful and retain distinct statuses. Infrastructure failures abort and are not scored.'
    save(output / 'summary.json', summary)
    print(json.dumps(summary), flush=True)
    if plan['smoke'] and any(counts[s] for s in ('empty_output','truncated','incomplete_output')):
        raise RuntimeError('Smoke generation was empty/incomplete; not ready for full run')


def launch(plan_path, log_path, python):
    with open(log_path, 'ab') as log:
        proc = subprocess.Popen([str(python), '-u', str(ROOT / 'scripts/run_quantumbencheval.py'), '--worker', str(plan_path)],
                                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            # Tee raw bytes so progress bars (carriage returns) render live and run.log stays complete.
            while chunk := os.read(proc.stdout.fileno(), 65536):
                log.write(chunk); log.flush()
                sys.stdout.buffer.write(chunk); sys.stdout.buffer.flush()
            return proc.wait()
        finally:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            proc.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(ROOT / 'configs/quantumbencheval.json'))
    parser.add_argument('--models', nargs='+', help='Manifest keys or all; aliases are not distinct models')
    parser.add_argument('--datasets', nargs='+')
    parser.add_argument('--run-id', default='main')
    parser.add_argument('--output-root', default=str(ROOT / 'runs/quantumbencheval_t1-6'))
    parser.add_argument('--gpus', default=os.getenv('CUDA_VISIBLE_DEVICES', '0'))
    parser.add_argument('--python', dest='python_override')
    parser.add_argument('--evaluation-python')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--resolve-revisions', action='store_true')
    parser.add_argument('--smoke', action='store_true', help='One task/sample per topic; unchanged token budget')
    parser.add_argument('--continue-on-error', action='store_true')
    parser.add_argument('--worker', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker: worker(args.worker); return 0
    os.chdir(ROOT)
    config, registry = load_config(args.config)
    keys = select(args.models, config['selected_models'], registry)
    topics = select(args.datasets, config['datasets'], [f'T{i}' for i in range(1,7)])
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.run_id): raise ValueError('Invalid run ID')
    if args.resolve_revisions:
        from huggingface_hub import HfApi
        errors = []
        for key in keys:
            model = registry[key]
            if 'hf_checkpoint' not in model or key in config['held_models'] or key in config['identity_blocks']: continue
            if key in config['revision_pins']: continue
            try:
                revision = model.get('historical_revision') or HfApi(token=os.getenv('HF_TOKEN') or os.getenv('HUGGINGFACE_HUB_TOKEN')).model_info(model['hf_checkpoint']).sha
                config['revision_pins'][key] = revision
                config.setdefault('revision_pin_provenance', {})[key] = {
                    'source': 'historical recorded commit' if model.get('historical_revision') else 'Resolved for NEW experiment; historical commit unknown',
                    'resolved_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
                save(args.config, config); print(key, revision)
            except Exception as exc:
                errors.append(key); print(key, str(exc), file=sys.stderr)
        return int(bool(errors))
    run = Path(args.output_root).resolve() / (args.run_id + ('-smoke' if args.smoke else ''))
    os.environ['CUDA_VISIBLE_DEVICES'] = args.gpus
    cache = run / 'cache'
    os.environ.update(HF_HOME=str(cache), HF_HUB_CACHE=str(cache / 'hub'), XDG_CACHE_HOME=str(cache / 'xdg'))
    eval_python = Path(args.evaluation_python or config['evaluation_python']).absolute()
    jobs = []
    for key in keys:
        model = registry[key]
        python = Path(args.python_override or config['python_overrides'].get(key, config['python'])).absolute()
        for topic in topics:
            _, data = load_dataset(ROOT / config['data_dir'], topic)
            output = run / key / topic
            plan = {'config': config, 'model': model, 'settings': effective(model, config, args), 'topic': topic,
                    'data_dir': str((ROOT / config['data_dir']).resolve()), 'dataset': data, 'output': str(output),
                    'cache': str(cache), 'python': str(python), 'evaluation_python': str(eval_python),
                    'cuda_visible_devices': args.gpus, 'smoke': args.smoke}
            jobs.append((plan, output / 'plan.json'))
            if args.dry_run:
                command = [str(python), '-u', str(ROOT / 'scripts/run_quantumbencheval.py'), '--worker', str(output / 'plan.json')]
                print(json.dumps({'model': model['identity'], 'dataset': topic, 'blockers': blockers(model, config),
                                  'command': shlex.join(command), 'plan': plan}, indent=2))
    if args.dry_run: return 0
    run.mkdir(parents=True, exist_ok=True)
    lock = open(run / '.lock', 'w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    summary, stopped = [], False
    for plan, path in jobs:
        row = {'model': plan['model']['identity'], 'key': plan['model']['key'], 'dataset': plan['topic'], 'output': plan['output']}
        if stopped:
            summary.append({**row, 'status': 'not_attempted'}); continue
        try:
            errors = blockers(plan['model'], config)
            if errors: raise RuntimeError('; '.join(errors))
            probe(Path(plan['python']), gpu='hf_checkpoint' in plan['model'])
            probe(eval_python, evaluation=True)
            required = []
            identity = plan['model']['identity']
            if identity.startswith('claude') or plan['topic'] == 'T3': required.append('ANTHROPIC_API_KEY')
            if identity.startswith('gemini') and not (os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY')): required.append('GEMINI_API_KEY')
            if identity == 'gpt-5': required += ['AZURE_OPENAI_API_KEY', 'AZURE_OPENAI_ENDPOINT']
            if plan['model']['assistant_implementation'].endswith('.OpenAIGPTAssistant') and not (os.getenv('OPEN_AI_API_KEY') or os.getenv('OPENAI_API_KEY')):
                required.append('OPENAI_API_KEY (or OPEN_AI_API_KEY)')
            missing = [k for k in required if not os.getenv(k)]
            if missing: raise RuntimeError('Missing credentials: ' + ', '.join(missing))
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and json.loads(path.read_text()) != plan: raise RuntimeError('Plan changed; use a new run ID')
            save(path, plan)
            if args.check: row['status'] = 'preflight_passed'
            else:
                print(f'Running {row["model"]} {row["dataset"]}; log: {path.parent / "run.log"}', flush=True)
                code = launch(path, path.parent / 'run.log', Path(plan['python']))
                if code: raise RuntimeError(f'Worker exited {code}; see run.log')
                row['status'] = 'completed'
        except KeyboardInterrupt:
            row['status'] = 'interrupted'; stopped = True
        except Exception as exc:
            row.update(status='failed', error=str(exc)); stopped = not args.continue_on_error
        summary.append(row)
        save(run / ('preflight.json' if args.check else 'summary.json'), summary)
    save(run / ('preflight.json' if args.check else 'summary.json'), summary)
    for row in summary: print(f'{row["key"]:20} {row["dataset"]} {row["status"]} {row.get("error", "")}')
    lock.close()
    return int(any(r['status'] in ('failed', 'interrupted', 'not_attempted') for r in summary))
