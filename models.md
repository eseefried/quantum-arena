# Model registry and run history

Last audited: **2026-09-09**. This is a snapshot, not a live dashboard.

Keep the exact recorded assistant ID when comparing results. A result file proves
that an evaluation was saved, not that every generation was nonempty or valid.
Parameter sizes below are published model-size labels unless otherwise specified;
B = billion, M = million. API-only model parameter counts are not recorded here as
known facts. Hugging Face links identify checkpoints, not proof of the revision
used in an old run: historical commit hashes were generally not saved.

## Open-weight models and RAG

| Recorded assistant ID(s) | Provider / specialization | Parameters | Hugging Face checkpoint | Notes |
|---|---|---|---|---|
| `meta-llama/Llama-3.1-8B` | Meta; base model | 8B | [Llama 3.1 8B](https://huggingface.co/meta-llama/Llama-3.1-8B) | Base checkpoint, not Instruct. New QCoder run uses Sonnet 4.6 judge. |
| `meta-llama/Llama-3.2-3B-Instruct` | Meta; instruction tuned | 3B | [Llama 3.2 3B Instruct](https://huggingface.co/meta-llama/Llama-3.2-3B-Instruct) | Separate model from 3.1 8B. |
| `google/gemma-3-4b-it` | Google; instruction tuned | 4B | [Gemma 3 4B IT](https://huggingface.co/google/gemma-3-4b-it) | Recorded local checkpoint. |
| `mistralai/Mistral-7B-Instruct-v0.3` | Mistral AI; instruction tuned | 7B | [Mistral 7B Instruct v0.3](https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3) | Recorded local checkpoint. |
| `mistral-small-3.2-24b-qiskit`, `mistral3` | Qiskit fine-tune of Mistral | 24B | [Mistral Small 3.2 24B Qiskit](https://huggingface.co/Qiskit/mistral-small-3.2-24b-qiskit) | Current factory routes both aliases to this default. Historical overrides/revisions remain unverified; Arena keeps separate rows. |
| `qwen2.5-coder-14b-qiskit`, `qwen` | Qiskit fine-tune of Qwen | 14B class | [Qwen2.5 Coder 14B Qiskit](https://huggingface.co/Qiskit/Qwen2.5-Coder-14B-Qiskit) | Current factory routes both aliases to this default. Do not merge historical runs solely from this routing. |
| `qiskit/granite-8b-qiskit` | IBM / Qiskit fine-tune | 8B | [Granite 8B Qiskit](https://huggingface.co/Qiskit/granite-8b-qiskit) | Historical HumanEval/QuanBench label; not proven identical to Granite 3.2. |
| `Qiskit/granite-3.2-8b-qiskit` | IBM / Qiskit fine-tune | 8B | [Granite 3.2 8B Qiskit](https://huggingface.co/Qiskit/granite-3.2-8b-qiskit) | QCoder label and current factory default. |
| `quantum-rag` | Custom retrieval + Granite generator | 8B generator + 30M embedder | [Generator](https://huggingface.co/Qiskit/granite-3.2-8b-qiskit), [embedder](https://huggingface.co/ibm-granite/granite-embedding-30m-english) | Pipeline, not a distinct trained checkpoint. Current defaults: top-k 4, first 2,000 corpus chunks, Qiskit 2.2 docs; generator attempts NF4 4-bit loading. Environment overrides can change these settings. QCoder startup encountered CUDA initialization failures. |
| `meta-llama/Llama-4-Scout-17B-16E-Instruct` | Meta; mixture of experts | 17B active / 109B total | [Llama 4 Scout](https://huggingface.co/meta-llama/Llama-4-Scout-17B-16E-Instruct) | **Archived / excluded** pending output verification. Historical HE Standard/Hard and QB44 files remain in `experiments/archived_results/scout_unverified/`. No generation caches found during audit. |

## API models

These runs use hosted APIs, not local Hugging Face weights. No verified public
parameter count is recorded for these models; do not substitute speculative sizes.

| Exact recorded / configured ID | Provider / API | Status and provenance |
|---|---|---|
| `gpt-5` | OpenAI via Azure Responses API | Historical results retained. Latest historical QCoder file: 211/335 outputs empty, 124 nonempty, 26 passing. Fresh rerun blocked by Azure `DeploymentNotFound` for deployment `gpt-5`; this does not establish global model retirement. |
| `claude-opus-4-6` | Anthropic Messages API | Historical HE Standard/Hard and both QuanBench variants. QCoder previously excluded at user request; new Fable plan explicitly includes QCoder. |
| `gemini-2.0-flash` | Google GenAI API | Historical QCoder only. API later explicitly reported this ID no longer available. Preserve original ID. |
| `gemini-3-flash-preview` | Google GenAI API | Historical results across all five datasets. Not established to be Gemini 3.6. |
| `gemini-3.6-flash` | Google GenAI API | New model entry. All five datasets saved, including QCoder (`results_20260909_174158.json`, Sonnet 4.6 judge). |
| `claude-fable-5-1` | Anthropic Messages API | Prepared for all five datasets; live smoke test returned nonempty Python. No final benchmark result files at this audit. Always-on adaptive thinking; adapter omits temperature, streams responses, extracts text only, rejects empty/unfinished responses. Launch script: `scripts/run_fable_all.sh`. |

Official references: [GPT-5](https://developers.openai.com/api/docs/models/gpt-5),
[Claude models](https://platform.claude.com/docs/en/models/overview),
[Fable 5.1](https://platform.claude.com/docs/en/models/fable-5-1/overview),
[Gemini models](https://ai.google.dev/gemini-api/docs/models).
Availability claims above come from this session's actual API responses; a model
listed by an API is not automatically a model we have benchmarked.

## Saved benchmark coverage

Generated from `experiments/results/**/results_*.json` on the audit date.
Numbers are task counts in the latest saved file for each model and dataset.
`—` means no saved final file, not necessarily no attempt. This table does not
certify output quality. Aliases stay separate intentionally.

| Recorded ID | HE Standard | HE Hard | QB44 | QB117 | QCoder |
|---|---:|---:|---:|---:|---:|
| `Qiskit/granite-3.2-8b-qiskit` | — | — | — | — | 67 |
| `claude-opus-4-6` | 151 | 151 | 44 | 117 | — |
| `gemini-2.0-flash` | — | — | — | — | 67 |
| `gemini-3-flash-preview` | 151 | 151 | 44 | 117 | 67 |
| `gemini-3.6-flash` | 151 | 151 | 44 | 117 | 67 |
| `google/gemma-3-4b-it` | 151 | 151 | 44 | 117 | 67 |
| `gpt-5` | 151 | 151 | 44 | 117 | 67 |
| `meta-llama/Llama-3.1-8B` | 151 | 151 | 44 | 117 | 67 |
| `meta-llama/Llama-3.2-3B-Instruct` | — | — | — | — | 67 |
| `mistral-small-3.2-24b-qiskit` | 151 | 151 | 44 | 117 | — |
| `mistral3` | — | — | — | — | 67 |
| `mistralai/Mistral-7B-Instruct-v0.3` | 151 | 151 | 44 | 117 | 67 |
| `qiskit/granite-8b-qiskit` | 151 | 151 | 44 | 117 | — |
| `quantum-rag` | 151 | 151 | 44 | 117 | — |
| `qwen` | — | — | — | — | 67 |
| `qwen2.5-coder-14b-qiskit` | 151 | 151 | 44 | 117 | — |

Standard/Hard each contain 151 tasks; QB44 has 44, QB117 has 117; QCoder has 67.
Most saved runs request five samples per task. QB44 and QB117 overlap: all 44
IDs occur in both, 36 prompts match exactly, eight differ, and all 44 test strings
differ. They are evaluation variants, not 161 wholly unique problems.

## Judge history (separate from candidate model identity)

| Judge ID | Use |
|---|---|
| `claude-sonnet-4-20250514` | Historical QCoder judge. Returned 404 during the September Llama run. Old completed results retained. |
| `claude-sonnet-4-6` | Current QCoder judge; confirmed available. New Llama 3.1 run and current Gemini/Fable commands use it. Structured `PASS`/`FAIL` tool response required. |

Scores judged by different models or response protocols are not strictly
comparable. Rejudging all saved outputs with one judge remains a separate task;
it has **not** been done. Fable as a candidate and Sonnet as judge are distinct
models within the same provider family.

## Change log

- **2026-09-08–09 — QCoder recovery:** replaced unavailable Sonnet 4 judge with
  Sonnet 4.6. API failures stop instead of becoming false verdicts. Generations
  are saved pending judgment; JSONL can contain multiple records per sample index.
  Use the latest record per index, or completed task JSON, for sample counts.
- **2026-09-09 — Gemini replacement:** started `gemini-3.6-flash` as a new entry.
  Do not rename `gemini-2.0-flash` or `gemini-3-flash-preview` results to 3.6.
- **2026-09-09 — Scout exclusion:** archived unverified results in the benchmark
  and Arena repositories. No claim that all Scout outputs were empty is established.
- **2026-09-09 — GPT rerun prepared, then held:** historical QCoder generation cap
  was 2,048 tokens; proposed fresh run uses 16,384 and isolated cache
  `cache/qcoder_gpt5_rerun_20260909`. Empty/incomplete detection added. Deployment
  lookup failed before benchmark generation. Token exhaustion is a possible,
  unconfirmed explanation for older empty outputs.
- **2026-09-09 — QuanBench selection repaired:** `--quanbench_variant` now reaches
  the loader. New caches use `cache/quanbench/QuanBench44/` and `QuanBench117/`.
  Legacy caches are retained and not automatically imported into these paths.
- **2026-09-09 — Fable prepared:** exact ID `claude-fable-5-1`; five datasets,
  five samples/task, 16,384 max response tokens. Script supplies temperature 1
  for config bookkeeping, but the adapter sends no temperature parameter.
  Thinking uses provider defaults. Smoke test only confirmed generation and
  Python syntax, not benchmark correctness.

## Record every future model change

Before launching a replacement, add a dated entry here and preserve old results.
Record the exact candidate ID, provider, HF URL and pinned commit if applicable,
Azure deployment separately from underlying model/version, parameter count source,
quantization/dtype, reasoning settings, effective sampling parameters, max token
budget, datasets/variants, cache location, judge ID/protocol, and run status.
Mark unknown historical settings as unknown. Never infer identical checkpoints
from a short alias or silently combine runs across replacements.

Local evidence: `scripts/run_benchmark.py`, `scripts/run_benchmark_qcoder.py`,
`assistants/`, `experiments/results/`, `cache/`, and the archived Scout directory.
