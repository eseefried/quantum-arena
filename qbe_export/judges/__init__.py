"""Optional judge transports for QuantumBenchEval T3. Default behaviour (Anthropic) is unchanged."""


def install_judge_provider(name):
    if name == 'anthropic':
        return
    if name == 'perplexity':
        from judges.perplexity import install
        install()
        return
    raise ValueError(f'Unknown QBE_JUDGE_PROVIDER {name!r}; expected anthropic or perplexity')


def install_generation_provider(name):
    """Candidate-generation transport for ONE scoped (model, topic); see judges/perplexity_generation.py."""
    if name == 'anthropic':
        return
    if name == 'perplexity':
        from judges.perplexity_generation import install
        install()
        return
    raise ValueError(f'Unknown QBE_GENERATION_PROVIDER {name!r}; expected anthropic or perplexity')
