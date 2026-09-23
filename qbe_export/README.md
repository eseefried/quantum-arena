# QuantumBenchEval leaderboard export

Test export — one finished model (`gemini36-flash`), plus everything needed to score/reproduce
without the rest of the AS-HybridQuantumBench repo. Files here are copies of files still in
active use in the source repo (`datasets/`, `configs/`, `qbe/`, `requirements-qbe.lock.txt`);
`results/gemini36-flash/` was *moved*, not copied — that model is fully done, nothing else
references its old location.

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
- `results/gemini36-flash/` — `T1/`..`T6/`, each with `samples/*.json` (one file per
  `<task_id>.<sample_index>.json`) and `summary.json`; plus a model-level `summary.json`
  combining all 6 topics.
- `t1_corrected/` — `build_graded_t1.py` (generates `QuantumBenchEval_T1_graded.json` from the
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

## `gemini36-flash` result headline

Original T1: **0% pass@1** (`{'incorrect': 82, 'candidate_error': 2, 'candidate_unsupported_import': 1}`).
Corrected T1 (`t1_corrected/gemini36-flash_t1_graded.json`): **71/85 (84%)** pass once the
undisclosed exact-match check is replaced with the closeness metric. Same underlying candidate
code, replayed, nothing regenerated -- this is purely a scoring-defect fix, not a re-run.

To reproduce the correction for another model: bring its `results/<model>/T1/samples/*.json`
here and run `python3 t1_corrected/replay_t1_graded.py <model-key> results/<model-key>`.
