"""Perplexity transport for CANDIDATE GENERATION of one scoped (model, topic) -- opt-in, exact-scope only.

Enabled with QBE_GENERATION_PROVIDER=perplexity plus QBE_GENERATION_SCOPE=<model-key>:<topic> (e.g. fable51:T3).
Anything outside that scope is untouched. The scope is mandatory so this can never silently reroute a model's
generations in a run that was meant to use the vendor's own API.

The unmodified ClaudeAssistant is used: its system prompt, single user message, max_tokens, Fable no-temperature
rule, stop_reason handling and the runner's completion classification are all exactly what the Anthropic path
uses. Only the client is swapped: while qbe.models.create builds the assistant, `anthropic.Anthropic` is replaced
by a shim whose messages.stream()/create() send the same request through
openai.OpenAI(base_url=https://api.perplexity.ai/v1).responses.create(...) and return an Anthropic-shaped response.

Only samples that have no cached generation are generated; cached generations and judgments are never touched.
Because this module sits outside qbe/ and assistants/ (which are hashed into the provenance fingerprint), the run
still resumes in place. The provider change is recorded per sample (generation.metadata) and per run
(generation_provenance.json, merged into provenance.json, with this module's SHA-256).

Any API error, truncation or empty output raises, which stops the worker before anything is cached (ClaudeAssistant
raises for Fable). Nothing is converted into an incorrect answer.

Serving through Perplexity under an Anthropic-style model ID is NOT claimed to be identical to Anthropic's own API:
the returned model ID and token usage are recorded so any difference is visible.
"""
import hashlib
import json
import os
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from judges.perplexity import API_KEY_ENV, BASE_URL, JudgeTransportError, _usage_dict, _utc

PROVIDER = 'perplexity'
MODEL_MAP = {'claude-fable-5-1': 'anthropic/claude-fable-5-1'}          # exact IDs only; unknown model => refuse
SERVING_NOTE = ('Generated via Perplexity under an Anthropic-style model ID. Identical serving behaviour to '
                "Anthropic's own API is not claimed; compare generation_model_returned and usage, not the ID.")
UNCHANGED = ('assistants.claude_assistant.ClaudeAssistant executed as-is: system prompt, user prompt, max_tokens, '
             'Fable no-temperature rule, stop_reason check and runner classification are unchanged; only the '
             'transport differs')
LAST = {}                                                             # returned model / response id of the latest call
active = {'on': False}


class _Block(SimpleNamespace):
    pass


def _to_anthropic_shape(response, requested_api_model):
    returned = getattr(response, 'model', None)
    if returned != requested_api_model:
        raise JudgeTransportError(f'returned model {returned!r} != requested {requested_api_model!r}')
    status = getattr(response, 'status', None)
    incomplete = getattr(getattr(response, 'incomplete_details', None), 'reason', None)
    if status == 'completed':
        stop_reason = 'end_turn'
    elif status == 'incomplete' and incomplete == 'max_output_tokens':
        stop_reason = 'max_tokens'                                    # the adapter raises on anything but end_turn
    else:
        raise JudgeTransportError(f'response.status={status!r} incomplete_details={incomplete!r}')
    texts = []
    for item in getattr(response, 'output', None) or []:
        if getattr(item, 'type', None) == 'message':
            texts += [part.text for part in item.content if getattr(part, 'type', None) == 'output_text']
    if not texts and stop_reason == 'end_turn':
        raise JudgeTransportError('completed response contained no output_text')
    usage = _usage_dict(getattr(response, 'usage', None))
    LAST.update(response_model=returned, response_id=response.id, usage=usage)
    return SimpleNamespace(content=[_Block(type='text', text=t) for t in texts], stop_reason=stop_reason,
                           id=response.id, model=returned,
                           usage=SimpleNamespace(input_tokens=usage.get('input_tokens'), output_tokens=usage.get('output_tokens')))


class _Stream:
    def __init__(self, thunk):
        self._thunk = thunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._thunk()


class _Messages:
    """Accepts exactly the request ClaudeAssistant builds for Fable; anything else fails loudly."""

    def __init__(self, client):
        self._client = client

    def _send(self, *, model, max_tokens, system, messages, **unexpected):
        if unexpected:
            raise JudgeTransportError(f'unsupported generation request fields: {sorted(unexpected)}')
        if model not in MODEL_MAP:
            raise JudgeTransportError(f'model {model!r} has no exact Perplexity mapping in MODEL_MAP')
        if len(messages) != 1 or messages[0].get('role') != 'user' or not isinstance(messages[0].get('content'), str):
            raise JudgeTransportError('expected a single user message with string content')
        api_model = MODEL_MAP[model]
        response = self._client.responses.create(
            model=api_model, instructions=system,
            input=[{'role': 'user', 'content': messages[0]['content']}], max_output_tokens=max_tokens)
        return _to_anthropic_shape(response, api_model)

    def create(self, **request):
        return self._send(**request)

    def stream(self, **request):
        return _Stream(lambda: self._send(**request))


class PerplexityAnthropicGenerationShim:
    """Stands in for anthropic.Anthropic(api_key=...) while the assistant is being constructed."""

    def __init__(self, timeout=900, max_retries=3, **_):
        key = os.environ.get(API_KEY_ENV)
        if not key:
            raise JudgeTransportError(f'{API_KEY_ENV} is not set')
        from openai import OpenAI
        self.messages = _Messages(OpenAI(api_key=key, base_url=BASE_URL, timeout=timeout, max_retries=max_retries))


def _scope():
    scope = os.environ.get('QBE_GENERATION_SCOPE', '')
    if scope.count(':') != 1 or not all(scope.split(':')):
        raise ValueError('QBE_GENERATION_PROVIDER=perplexity requires QBE_GENERATION_SCOPE=<model-key>:<topic>, e.g. fable51:T3')
    return tuple(scope.split(':'))


def _tally(samples_dir):
    counts = Counter()
    for path in Path(samples_dir).glob('*.json'):
        record = json.loads(path.read_text())
        generation = record.get('generation') or record.get('failed_generation')
        if generation:
            counts[(generation.get('metadata') or {}).get('generation_provider', 'anthropic')] += 1
    return dict(counts)


def wrap_create(original_create):
    def create(model, settings, config, cache):
        if not active['on']:
            return original_create(model, settings, config, cache)
        import anthropic
        real, had_key = anthropic.Anthropic, os.environ.get('ANTHROPIC_API_KEY')
        anthropic.Anthropic = PerplexityAnthropicGenerationShim
        if not had_key:                                               # ClaudeAssistant insists on a key it will never use
            os.environ['ANTHROPIC_API_KEY'] = 'unused-generation-goes-via-perplexity'
        try:
            assistant, tracking = original_create(model, settings, config, cache)
        finally:
            anthropic.Anthropic = real
            if not had_key:
                os.environ.pop('ANTHROPIC_API_KEY', None)
        generate = assistant.generate_code

        def tagged(*args, **kwargs):
            LAST.clear()
            generations = generate(*args, **kwargs)
            for generation in generations:
                generation.metadata = {**(generation.metadata or {}), 'generation_provider': PROVIDER,
                                       'generation_model_requested_config': model['identity'],
                                       'generation_model_requested_api': MODEL_MAP.get(model['identity']),
                                       'generation_model_returned': LAST.get('response_model'),
                                       'generation_usage': LAST.get('usage'),
                                       'generation_serving_note': SERVING_NOTE}
            return generations
        assistant.generate_code = tagged
        return assistant, tracking
    return create


def wrap_worker(original_worker, save, scope):
    module_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

    def worker(plan_path):
        plan = json.loads(Path(plan_path).read_text())
        if (plan['model']['key'], plan['topic']) != scope:
            return original_worker(plan_path)
        if not os.environ.get(API_KEY_ENV):
            raise JudgeTransportError(f'QBE_GENERATION_PROVIDER=perplexity but {API_KEY_ENV} is not set in this shell '
                                      f'(a running shell does not re-read ~/.bashrc: run `source ~/.bashrc`)')
        output = Path(plan['output'])
        sidecar_path = output / 'generation_provenance.json'
        sidecar = json.loads(sidecar_path.read_text()) if sidecar_path.exists() else {'events': []}
        before = _tally(output / 'samples')
        if sidecar.get('current_provider', 'anthropic') != PROVIDER:
            sidecar['events'].append({
                'kind': 'provider_transition', 'at_utc': _utc(), 'provider_before': sidecar.get('current_provider', 'anthropic'),
                'provider_after': PROVIDER, 'model': plan['model']['identity'], 'topic': plan['topic'],
                'requested_api_model': MODEL_MAP.get(plan['model']['identity']), 'base_url': BASE_URL,
                'max_tokens': plan['settings']['max_tokens'], 'unchanged': UNCHANGED,
                'samples_generated_before': before, 'transport_module_sha256': module_sha,
                'reason': os.environ.get('QBE_GENERATION_REASON', 'operator selected QBE_GENERATION_PROVIDER=perplexity'),
                'serving_note': SERVING_NOTE})
        sidecar['current_provider'] = PROVIDER
        session = {'kind': 'session', 'started_utc': _utc(), 'provider': PROVIDER}
        sidecar['events'].append(session)
        output.mkdir(parents=True, exist_ok=True)
        save(sidecar_path, sidecar)                                   # written first so even a hard kill leaves the record
        active['on'] = True
        try:
            return original_worker(plan_path)
        finally:
            active['on'] = False
            after = _tally(output / 'samples')
            session['ended_utc'] = _utc()
            session['generated_by_provider_after'] = after
            session['generated_this_session'] = after.get(PROVIDER, 0) - before.get(PROVIDER, 0)
            save(sidecar_path, sidecar)
            provenance_path = output / 'provenance.json'
            if provenance_path.exists():
                provenance = json.loads(provenance_path.read_text())
                provenance['generation_provenance'] = sidecar
                save(provenance_path, provenance)
    return worker


def install():
    import qbe.models as models
    import qbe.runner as runner
    scope = _scope()
    models.create = wrap_create(models.create)
    runner.worker = wrap_worker(runner.worker, runner.save, scope)
