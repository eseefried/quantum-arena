# Minimal T2/T6 sensitivity evaluator

This directory contains the separate `scoring_v2` evaluator. Original code, datasets, and
model output records remain under `qbe_export/` and are never overwritten.

Results are in:
`/home/ejx/quantum/quantum-ai-assistants-benchmark/iclr/audit/scoring_v2/`

- `prepare.py`: creates only the 25 authorized assertion deletions, preserves all remaining
  test bytes, and records the pre-declared protocol and source hashes. The three excluded
  T2 tasks remain available for reference/replay diagnostics, but are excluded from v2 scores.
- `original_child.py`: byte-identical copy of the supplied original execution child.
- `paired_child.py`: executes each saved function once and checks the same unnormalized
  return against original and v2 assertions. This avoids attributing independent simulator
  draws to assertion removal. Recursive entry-point calls still execute normally.
- `run.py`: runs all T2/T6 references or saved samples in sanitized subprocess environments
  with original timeouts; retains generation-terminal failures. No adapters, generation,
  or judge calls. Uses an isolated Python environment with the recorded core dependencies.
- `summarize.py`: writes the requested scores/CIs, flips, exclusions, reference checks,
  original-vs-replay drift diagnostics, and report. Primary original scores are historical;
  paired comparisons are reported separately. No retries or pass overrides.

From the repository root, after the one-time pre-declaration:

```sh
/tmp/qbe-scoring-v2-env/bin/python scoring_v2/run.py references --workers 8
/tmp/qbe-scoring-v2-env/bin/python scoring_v2/run.py samples --workers 16
/tmp/qbe-scoring-v2-env/bin/python scoring_v2/summarize.py
/tmp/qbe-scoring-v2-env/bin/python -m unittest discover -s scoring_v2 -p test_scoring.py
```

Completed evaluations are resumed from verified cached raw records, not rerun to seek
better outcomes. `prepare.py` refuses to replace an existing pre-declaration.
See `environment.json` in the result directory for installed versions. The replay runs on
x86_64; source provenance was aarch64. Differences from historical outcomes are reported.
