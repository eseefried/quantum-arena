"""Original adapters with explicit checkpoints and completion instrumentation."""
import importlib
import os


def create(model, settings, config, cache):
    from assistants.base_assistant import GenerationConfig
    generation = GenerationConfig(temperature=settings['temperature'], num_samples=settings['samples'],
                                  max_tokens=settings['max_tokens'], top_p=settings['top_p'])
    generation.effective_max_tokens = settings['max_tokens']
    module, name = model['assistant_implementation'].rsplit('.', 1)
    cls = getattr(importlib.import_module(module), name)
    tracking = {}
    if 'hf_checkpoint' in model:
        import torch
        from huggingface_hub import snapshot_download
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA unavailable; CPU fallback forbidden')
        revision = config['revision_pins'][model['key']]
        token = os.getenv('HF_TOKEN') or os.getenv('HUGGINGFACE_HUB_TOKEN')
        if not token and model['hf_checkpoint'].startswith(('meta-llama/', 'google/gemma')):
            raise RuntimeError('Export HF_TOKEN or HUGGINGFACE_HUB_TOKEN in the launch shell for this gated checkpoint')
        path = snapshot_download(model['hf_checkpoint'], revision=revision, cache_dir=str(cache / 'hub'), token=token)
        if name == 'GraniteQiskitAssistant':
            assistant = cls(model_path=path, device='cuda:0', config=generation, device_map={'': 'cuda:0'})
        else:
            argument = 'model_path' if name in ('Mistral3QiskitAssistant', 'Qwen25QiskitAssistant') else 'model_id'
            assistant = cls(**{argument: path}, config=generation, torch_dtype=torch.bfloat16,
                            device_map={'': 'cuda:0'}, attn_implementation='sdpa')
        if any(p.device.type != 'cuda' for p in assistant.model.parameters()):
            raise RuntimeError('Model weights are not entirely on CUDA')
        assistant.model_name = model['identity']
        original = assistant.model.generate

        def tracked_generate(*args, **kwargs):
            output = original(*args, **kwargs)
            tokens = output[0][kwargs['input_ids'].shape[-1]:]
            eos = kwargs.get('eos_token_id', assistant.model.generation_config.eos_token_id)
            eos = eos if isinstance(eos, list) else [eos]
            cap = kwargs['max_new_tokens']
            tracking.update(generated_tokens=len(tokens), max_new_tokens=cap,
                            truncated=bool(len(tokens) >= cap and (not len(tokens) or int(tokens[-1]) not in eos)),
                            raw_text=assistant.tokenizer.decode(tokens, skip_special_tokens=False),
                            generation_defaults=assistant.model.generation_config.to_dict(),
                            effective_arguments={k: v for k, v in kwargs.items()
                                                 if isinstance(v, (int, float, str, bool, type(None)))})
            return output
        assistant.model.generate = tracked_generate
    else:
        options = {}
        if name == 'OpenAIGPTAssistant':
            options['reasoning_effort'] = settings['reasoning']
        assistant = cls(model_name=model['identity'], config=generation, **options)
        if name == 'ClaudeAssistant':
            owner, method = assistant.client.messages, 'create'
        elif name == 'GeminiAssistant':
            owner, method = assistant.client.models, 'generate_content'
        else:
            owner, method = assistant.client.responses, 'create'
        original = getattr(owner, method)

        def tracked_request(*args, **kwargs):
            result = original(*args, **kwargs)
            if name == 'GeminiAssistant':
                candidates = getattr(result, 'candidates', []) or []
                finish = str(getattr(candidates[0], 'finish_reason', 'UNKNOWN')) if candidates else 'UNKNOWN'
                raw = getattr(result, 'text', '') or ''
                truncated = 'MAX_TOKENS' in finish
                complete = finish in ('STOP', 'FinishReason.STOP')
            elif name == 'ClaudeAssistant':
                finish = result.stop_reason
                raw = '\n'.join(b.text for b in result.content if b.type == 'text')
                truncated, complete = finish == 'max_tokens', finish == 'end_turn'
            else:
                finish = result.status
                raw = getattr(result, 'output_text', '') or ''
                reason = getattr(getattr(result, 'incomplete_details', None), 'reason', None)
                truncated, complete = reason == 'max_output_tokens', finish == 'completed'
                tracking['incomplete_reason'] = reason
            tracking.update(raw_text=raw, truncated=truncated, finish_reason=finish, completion_verified=complete,
                            response_model=getattr(result, 'model', getattr(result, 'model_version', None)),
                            response_id=getattr(result, 'id', None))
            return result
        setattr(owner, method, tracked_request)
    return assistant, tracking


def classify(generation, tracking):
    if tracking.get('truncated'):
        return 'truncated'
    if not generation.success:
        if tracking and not tracking.get('raw_text', '').strip():
            return 'empty_output'
        return 'incomplete_output' if tracking else 'generation_failure'
    if not generation.code.strip():
        return 'empty_output'
    if tracking.get('completion_verified') is False:
        return 'incomplete_output'
    return 'generated'
