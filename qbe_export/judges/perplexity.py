"""Perplexity transport for the QuantumBenchEval T3 judge (opt-in: QBE_JUDGE_PROVIDER=perplexity).

qbe.evaluate.judge_t3 is executed UNMODIFIED, so the judge prompt, rubric-score schema, token budget
(config['judge']['max_tokens']), temperature, score validation and the deterministic energy-accuracy
override are exactly what the Anthropic path uses. Only the API call is swapped: for the duration of one
judge_t3 call, `anthropic.Anthropic` is replaced by a shim that sends the same request through
openai.OpenAI(base_url=https://api.perplexity.ai/v1).responses.create(...) and hands back an
Anthropic-shaped response. The shim is restored afterwards, so candidate generation by Claude models in the
same process is never re-routed.

This module lives outside qbe/ and assistants/ on purpose: those directories are hashed into every run's
provenance fingerprint, and changing them would stop every existing run from resuming in place. Instead the
provider transition is recorded explicitly (per sample, in judge_provenance.json, and merged into
provenance.json), and this file's own SHA-256 is recorded with it.

Any API error, truncation or malformed verdict raises, which the worker records as `judge_failure` (the
sample stays unjudged and the cached generation is kept). Nothing is ever converted into an incorrect answer.

Serving through Perplexity under an Anthropic-style model ID is NOT claimed to be identical to Anthropic's
own API; the returned model ID is recorded so any difference is visible.
"""
import hashlib
import json
import os
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

PROVIDER = 'perplexity'
BASE_URL = 'https://api.perplexity.ai/v1'
API_KEY_ENV = 'PERPLEXITY_API_KEY'
REQUESTED_MODEL = 'anthropic/claude-sonnet-4-6'
SERVING_NOTE = ('Requested via Perplexity under an Anthropic-style model ID. Identical serving behaviour to '
                "Anthropic's own API is not claimed; compare judge_model_returned and the scores, not the ID.")
UNCHANGED = ('qbe.evaluate.judge_t3 executed as-is: prompt, rubric schema, max_tokens, temperature, score '
             'validation and deterministic energy scoring are unchanged; only the transport differs')


class JudgeTransportError(RuntimeError):
    pass


def validate_against_schema(value, schema, path='$'):
    """Minimal JSON-schema check for the shapes the judge uses (object/integer/string/enum)."""
    kind = schema.get('type')
    if kind == 'object':
        if not isinstance(value, dict):
            raise JudgeTransportError(f'{path}: expected object')
        properties = schema.get('properties', {})
        for key in schema.get('required', []):
            if key not in value:
                raise JudgeTransportError(f'{path}: missing required {key!r}')
        if schema.get('additionalProperties') is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                raise JudgeTransportError(f'{path}: unexpected properties {extra}')
        for key, sub in properties.items():
            if key in value:
                validate_against_schema(value[key], sub, f'{path}.{key}')
    elif kind == 'integer':
        if isinstance(value, bool) or not isinstance(value, int):
            raise JudgeTransportError(f'{path}: expected integer')
    elif kind == 'string':
        if not isinstance(value, str):
            raise JudgeTransportError(f'{path}: expected string')
        if 'enum' in schema and value not in schema['enum']:
            raise JudgeTransportError(f'{path}: {value!r} not in {schema["enum"]}')


class _Usage:
    def __init__(self, data):
        self._data = data

    def model_dump(self):
        return dict(self._data)


def _usage_dict(usage):
    if usage is None:
        return {}
    if hasattr(usage, 'model_dump'):
        return usage.model_dump()
    return dict(usage) if isinstance(usage, dict) else {}


def _to_anthropic_shape(response, tool):
    returned = getattr(response, 'model', None)
    if returned != REQUESTED_MODEL:
        raise JudgeTransportError(f'returned model {returned!r} != requested {REQUESTED_MODEL!r}')
    status = getattr(response, 'status', None)
    if status != 'completed':
        raise JudgeTransportError(f'response.status={status!r} (incomplete_details='
                                  f'{getattr(response, "incomplete_details", None)!r})')
    calls = [item for item in (getattr(response, 'output', None) or []) if getattr(item, 'type', None) == 'function_call']
    if len(calls) != 1 or getattr(calls[0], 'name', None) != tool['name']:
        raise JudgeTransportError(f'expected exactly one function_call named {tool["name"]!r}, '
                                  f'got {[getattr(c, "name", None) for c in calls]!r}')
    try:
        arguments = json.loads(calls[0].arguments)
    except (TypeError, ValueError) as exc:
        raise JudgeTransportError(f'function_call arguments are not valid JSON: {exc}') from exc
    validate_against_schema(arguments, tool['input_schema'])
    block = SimpleNamespace(type='tool_use', name=tool['name'], input=arguments)
    return SimpleNamespace(content=[block], stop_reason='tool_use', id=response.id, model=returned,
                           usage=_Usage(_usage_dict(getattr(response, 'usage', None))))


class _Messages:
    """Accepts exactly the request judge_t3 sends; anything else fails loudly instead of being mistranslated."""

    def __init__(self, client):
        self._client = client

    def create(self, *, model, max_tokens, messages, tools, tool_choice, extra_body=None, **unexpected):
        if unexpected:
            raise JudgeTransportError(f'unsupported judge request fields: {sorted(unexpected)}')
        if len(messages) != 1 or messages[0].get('role') != 'user' or not isinstance(messages[0].get('content'), str):
            raise JudgeTransportError('expected a single user message with string content')
        if len(tools) != 1 or tool_choice.get('type') != 'tool' or tool_choice.get('name') != tools[0]['name']:
            raise JudgeTransportError('expected one tool, forced by tool_choice')
        temperature = (extra_body or {}).get('temperature')
        if temperature is None:
            raise JudgeTransportError('judge temperature missing from request')
        tool = tools[0]
        response = self._client.responses.create(
            model=REQUESTED_MODEL,
            input=[{'role': 'user', 'content': messages[0]['content']}],
            temperature=temperature,
            max_output_tokens=max_tokens,
            tools=[{'type': 'function', 'name': tool['name'], 'description': tool.get('description', ''),
                    'parameters': tool['input_schema'], 'strict': True}],
            tool_choice={'type': 'function', 'name': tool['name']},
            parallel_tool_calls=False)
        return _to_anthropic_shape(response, tool)


class PerplexityAnthropicShim:
    """Stands in for anthropic.Anthropic(timeout=..., max_retries=...) during one judge call."""

    def __init__(self, timeout=120, max_retries=2, **_):
        key = os.environ.get(API_KEY_ENV)
        if not key:
            raise JudgeTransportError(f'{API_KEY_ENV} is not set')
        from openai import OpenAI
        self.messages = _Messages(OpenAI(api_key=key, base_url=BASE_URL, timeout=timeout, max_retries=max_retries))


def judge_via_perplexity(original_judge_t3, shim=PerplexityAnthropicShim):
    def judge(task, code, execution, config):
        import anthropic
        real = anthropic.Anthropic
        anthropic.Anthropic = shim
        try:
            result = original_judge_t3(task, code, execution, config)
        finally:
            anthropic.Anthropic = real
        result['judge_provider'] = PROVIDER
        result['judge_model_requested_config'] = config['model']
        result['judge_model_requested_api'] = REQUESTED_MODEL
        result['judge_model_returned'] = result.get('response_model')
        result['judge_serving_note'] = SERVING_NOTE
        return result
    return judge


def _utc():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _tally(samples_dir):
    counts = Counter()
    for path in Path(samples_dir).glob('*.json'):
        record = json.loads(path.read_text())
        if record.get('status') == 'judged' and isinstance(record.get('judge'), dict):
            counts[record['judge'].get('judge_provider', 'anthropic')] += 1
        elif record.get('status') == 'judge_failure':
            counts['judge_failure'] += 1
    return dict(counts)


def wrap_worker(original_worker, save):
    """Record the provider (and any transition) around each T3 worker session."""
    module_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

    def worker(plan_path):
        plan = json.loads(Path(plan_path).read_text())
        if plan['topic'] != 'T3':
            return original_worker(plan_path)
        if not os.environ.get(API_KEY_ENV):
            # Fail before any generation is paid for and before any transition is recorded.
            raise JudgeTransportError(f'QBE_JUDGE_PROVIDER=perplexity but {API_KEY_ENV} is not set in this shell '
                                      f'(a running shell does not re-read ~/.bashrc: run `source ~/.bashrc`)')
        output = Path(plan['output'])
        sidecar_path = output / 'judge_provenance.json'
        sidecar = json.loads(sidecar_path.read_text()) if sidecar_path.exists() else {'events': []}
        before = _tally(output / 'samples')
        provider_before = sidecar.get('current_provider', 'anthropic')
        if provider_before != PROVIDER:
            sidecar['events'].append({
                'kind': 'provider_transition', 'at_utc': _utc(), 'provider_before': provider_before,
                'provider_after': PROVIDER, 'judge_config': plan['config']['judge'],
                'requested_api_model': REQUESTED_MODEL, 'base_url': BASE_URL, 'unchanged': UNCHANGED,
                'samples_judged_before': before, 'transport_module_sha256': module_sha,
                'reason': os.environ.get('QBE_JUDGE_REASON', 'operator selected QBE_JUDGE_PROVIDER=perplexity'),
                'serving_note': SERVING_NOTE})
        sidecar['current_provider'] = PROVIDER
        session = {'kind': 'session', 'started_utc': _utc(), 'provider': PROVIDER}
        sidecar['events'].append(session)
        output.mkdir(parents=True, exist_ok=True)
        save(sidecar_path, sidecar)  # written first so even a hard kill leaves the record
        try:
            return original_worker(plan_path)
        finally:
            after = _tally(output / 'samples')
            session['ended_utc'] = _utc()
            session['judged_by_provider_after'] = after
            session['judged_this_session'] = after.get(PROVIDER, 0) - before.get(PROVIDER, 0)
            save(sidecar_path, sidecar)
            provenance_path = output / 'provenance.json'
            if provenance_path.exists():
                provenance = json.loads(provenance_path.read_text())
                provenance['judge_provenance'] = sidecar
                save(provenance_path, provenance)
    return worker


def install():
    import qbe.evaluate as evaluate
    import qbe.runner as runner
    runner.judge_t3 = judge_via_perplexity(evaluate.judge_t3)
    runner.worker = wrap_worker(runner.worker, runner.save)
