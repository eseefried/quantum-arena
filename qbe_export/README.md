# QuantumBenchEval leaderboard export

Eight finished models (all 6 topics, 480/480 samples each), plus everything needed to score/reproduce
without the rest of the AS-HybridQuantumBench repo: `astra`, `fable51`, `gemini3-flash`, `gemini31-pro`,
`gemini36-flash`, `gemma3-4b`, `llama32-3b`, `mistral7b`. `results/MANIFEST.json` lists per-model, per-topic
completeness, headline numbers, T3 provider splits and the corrected-T1 numbers -- read it first.

Files here are copies of files still in use in the source repo (`datasets/`, `configs/`, `qbe/`,
`judges/`, `requirements-qbe.lock.txt`), and `results/<model>/` for every model except `gemini36-flash`
is a byte-verified copy of `runs/quantumbencheval_t1-6/<model>/` (`gemini36-flash` was moved here and lives
only here). Models still running (granite32, qwen-qiskit) and not yet started (mistral-qiskit, opus46, ...)
are deliberately absent. Not yet corrected: the T2 `evaluation_cost` and T6 `reproducibility` scoring artifacts
(see the source repo's docs); T2/T6 numbers here are the original scoring.

## Layout

- `datasets/QuantumBenchEval_T1..T6.json` — the 6 topics, 96 tasks total (T1=17, T2=15, T3=15,
  T4=15, T5=17, T6=17). Each task: `task_id`, `prompt`, `entry_point`, `required_outputs`,
  `test` (assertion script for T1/T2/T4/T5/T6; a JSON rubric string for T3), `canonical_solution`
  (reference only, never shown to candidates).
- `datasets/QuantumBenchEval_T1_graded.json` — **corrected T1 variant**. The original T1 test
  hard-asserts exact `shots`/`optimizer_calls` values never disclosed to the candidate (only
  "report" is asked for), which deflates every model's T1 score toward 0% regardless of whether
  the actual Max-Cut answer is correct. This variant keeps every real correctness check
  (`cut_value`, probability ranges, circuit depth, graph structure) and replaces only those two
  assertions with a reported closeness ratio (`min(actual,target)/max(actual,target)`), gating
  nothing. See `t1_corrected/`.
- `configs/quantumbencheval.json` — the executable config: `selected_models` (roster), `samples`
  (5/task), `temperature` (0.8), `max_tokens` (16384 default) + `max_tokens_overrides` (per-model
  ceiling raise — some reasoning models draw invisible "thinking" tokens from the same budget as
  visible code and need more room), `revision_pins` (exact HF commits), `judge` (T3 judge model/
  temperature/max_tokens), `timeouts` (per-topic).
- `configs/quantumbencheval_models.proposed.json` — the model registry: exact checkpoint/API
  identity per key (e.g. `gemini36-flash` -> `gemini-3.6-flash`), adapter class, historical
  settings evidence.
- `qbe/` — the scorer. `data.py` (dataset loading, candidate-facing prompt construction with
  reference fields stripped), `evaluate.py` (sandboxed execution + T3 judge call), `eval_child_v2.py`
  (runs in the sandboxed subprocess; classifies import failures into `candidate_unsupported_import`
  (scored, e.g. hallucinated/removed API) vs `evaluation_environment_failure` (infra problem,
  not scored) vs `evaluation_crash` (subprocess killed by a signal, e.g. a native segfault --
  scored, not fatal, distinguished via a phase marker written before each risky exec)), `runner.py`
  (orchestration, pass@k, summary aggregation), `models.py` (per-adapter generation + completion
  classification, e.g. `truncated`/`empty_output`).
- `requirements-qbe.lock.txt` — the evaluation environment's locked package versions (Qiskit
  1.4.5, qiskit-aer 0.17.2, qiskit-algorithms 0.3.1, qiskit-optimization 0.6.1, PennyLane 0.45.1,
  dimod, neal, plus the generation stack -- Transformers/PyTorch -- since generation and
  evaluation now share one environment).
- `results/<model>/` — `T1/`..`T6/`, each with `samples/*.json` (one file per
  `<task_id>.<sample_index>.json`), `summary.json`, `plan.json`, `provenance.json` (fingerprint of plan +
  environment + source hashes + dataset), `run.log`; plus a model-level `summary.json` combining all 6 topics
  (for T3 it also records `generation_providers` / `judge_providers`). `plan.json`/`provenance.json` keep the
  original run-id absolute paths on purpose (they are part of the fingerprint).
- `results/MANIFEST.json` — machine-readable index of the above.
- `judges/` — the optional T3 transports used when Anthropic credits ran out (`perplexity.py` judge,
  `perplexity_generation.py` candidate generation for one scoped model/topic). Their SHA-256 is recorded in
  each affected run's `judge_provenance.json` / `generation_provenance.json`.
- `astra_t3_fix/` — `eval_child_v2.py` (+ `.diff` against `qbe/eval_child_v2.py`, + its test): follows
  `raise ImportError(...) from exc` chains so a candidate hiding a missing module is
  `candidate_unsupported_import`, not an environment failure. Only astra's T3 was evaluated with it (the
  earlier astra T3 attempt aborted on exactly that case and was discarded). No other model's results can
  differ: the case aborted a run before the fix.
- `t1_corrected/<model>_t1_graded.json` — corrected-T1 replay for every model in `results/`.
  `build_graded_t1.py` (generates `QuantumBenchEval_T1_graded.json` from the
  original T1 file, never modifies it), `replay_t1_graded.py` (replays a model's already-generated
  T1 code against the corrected test -- no regeneration needed), `gemini36-flash_t1_graded.json`
  (the computed result).

## Sample record status values

`passed` / `incorrect` (T1/T2/T4/T5/T6), `judged` (T3 -- always, no pass/fail, only a rubric
score), `candidate_error`, `candidate_unsupported_import`, `evaluation_crash`,
`evaluation_timeout`, `empty_output` / `truncated` / `incomplete_output`, and
`evaluation_environment_failure` (aborts that dataset for that model; deliberately unscored, so
never appears in a *finished* `summary.json`).

## `summary.json` fields

`counts` (status histogram), `execution_status_counts`, `unsupported_import_modules`; for
T1/T2/T4/T5/T6: `pass_at_k` (k=1, k=5); for T3: `mean_rubric_score` / `rubric_maximum`
(Sonnet-judged; energy-accuracy criterion is checked deterministically against the executed
output, not inferred from the judge).

## Corrected T1 (same candidate code, replayed; nothing regenerated)

| model | original T1 pass | graded T1 pass |
|---|---|---|
| astra | 0/85 | 80/85 |
| fable51 | 0/85 | 80/85 |
| gemini36-flash | 0/85 | 71/85 |
| gemini31-pro | 1/85 | 52/85 |
| gemini3-flash | 0/85 | 13/85 |
| gemma3-4b | 0/85 | 0/85 |
| llama32-3b | 0/85 | 0/85 |
| mistral7b | 0/85 | 0/85 |

The three small local models are 0 under both scorings because their code never reaches the shots/optimizer
check (syntax errors, removed APIs such as `from qiskit import Aer`); the graded statuses equal the originals.
For llama32-3b, 2 samples were originally `truncated`; their partial code was replayed and reported
`candidate_error` -- pass counts are unaffected.

## T3 provenance you must show alongside the number

- `fable51` T3: generation 70 Anthropic API + 5 Perplexity (all of `t3_14`); judge 70 Anthropic + 5 Perplexity.
- `gemini3-flash` T3: judge 74 Perplexity + 1 Anthropic.
- `astra` T3: judge 75 Perplexity; evaluated with `astra_t3_fix/eval_child_v2.py`.
- All other T3 results: Anthropic `claude-sonnet-4-6` judge, vendor-API generation.
Perplexity-served judgments are NOT claimed identical to Anthropic's own API (a two-sample live check moved individual
criteria by up to a point); read `judge.judge_provider` per sample and do not silently pool across providers.

To reproduce the correction for another model: bring its `results/<model>/T1/samples/*.json`
here and run `python3 t1_corrected/replay_t1_graded.py <model-key> results/<model-key> <absolute path to a python with the evaluation stack>`.
