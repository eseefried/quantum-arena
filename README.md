# Quantum Arena

A public leaderboard comparing frontier LLMs and quantum-specific coding assistants
on Qiskit code generation, across QiskitHumanEval, QuanBench, and QCoder.

Live site: enable GitHub Pages (Settings → Pages → Source: **GitHub Actions**) and it
will publish at `https://<your-username>.github.io/quantum-arena/` on the next push to `main`.

## How it works

```
data/results/          per-model experiment output (from the benchmark framework)
data/benchmarks/       task metadata (category / difficulty) used to enrich results
scripts/
  export_leaderboard.py   computes pass@k + reads confidence intervals, writes:
leaderboard/
  leaderboard_summary.json   one row per (model, dataset): pass@1/3/5, CI, task count, last run date
  leaderboard_details.json   one row per (model, dataset, task): for the category drill-down / problem view
  index.html / leaderboard.js   the Arena page: leaderboard + per-problem heatmap (reads the two JSON files)
  models.html / models.js    the Models page: provider/openness/parameter-count reference table
  styles.css                 shared styling for both pages
  assets/ornl-logo.png       logo shown in the shared top nav bar
.github/workflows/leaderboard-pages.yml   runs the export script and deploys leaderboard/ to Pages
```

All pass@k math and confidence-interval computation happens in Python, in
`export_leaderboard.py` — the same numbers the benchmark run itself produced.
The JavaScript only sorts, filters, and renders those precomputed numbers, so
the website can never disagree with the underlying evaluation code.

## Adding new results

Drop a new `results_*.json` file under `data/results/<model>/<benchmark>/` (same
shape the benchmark framework already produces) and push to `main`. The Actions
workflow re-runs the export and redeploys automatically — no manual JSON
generation or commit of generated files required.

## Local preview

```bash
python3 scripts/export_leaderboard.py   # regenerate leaderboard/leaderboard_*.json
cd leaderboard && python3 -m http.server 8000
# open http://localhost:8000
```

## Notes / known gaps

- `QCoder` results are included but have no category/difficulty metadata yet
  (that dataset's task file wasn't copied over) — its rows show as "Uncategorized".
- Confidence intervals (`data/results/confidence_intervals.json`) only cover a
  subset of models; others show a plain point estimate with no shaded range.
- A few models had more than one recorded run for the same dataset (e.g. reruns
  on different dates); the export script keeps only the most recent by timestamp.
- The Models page's Provider/Open/Parameters columns are hand-maintained in
  `leaderboard/models.js` (`MODEL_META`) since that metadata isn't part of any
  benchmark result file. Fine-tuned/custom entries with unconfirmed specs show
  "—"; update that table when adding a new model.

## QCoder judge provenance

The LLaMA-3.1-8B run dated 2026-09-09 contains 67 tasks with five samples
each, judged by `claude-sonnet-4-6`. Earlier QCoder runs used
`claude-sonnet-4-20250514`; comparisons therefore span different judge versions.
The new runner uses structured PASS/FAIL verdicts. The raw result file preserves
the judge model at both run and sample level. Earlier results have not been rejudged.

Gemini 3.6 Flash now has saved results for all five datasets (2026-09-09).
Its QCoder run also uses `claude-sonnet-4-6`; older Gemini IDs remain separate.
See [models.md](models.md) for the model registry and change history.

## Complete-model publication policy

Arena publishes only models with all five datasets: HumanEval Standard (151),
HumanEval Hard (151), QuanBench44 (44), QuanBench117 (117), and QCoder (67),
with five samples and boolean verdicts per task. Both summary and detail exports
use this filter. Missing coverage is printed during export. Completion describes
recorded coverage, not correctness or freedom from evaluation-environment errors.
Aliases are not merged without checkpoint verification.

Gemini 2.0 Flash was removed from active leaderboard inputs on 2026-09-10;
its QCoder files are preserved in `data/archived_results/gemini-2.0-flash/`.
Other incomplete models retain their source files but are hidden by the filter.

## QuantumBenchEval local preview

Run `python3 scripts/export_quantumbencheval.py`, then serve `leaderboard/` with
`python3 -m http.server 8000 --bind 127.0.0.1 --directory leaderboard` and open
http://localhost:8000/index.html?collection=qbe. Generate the original Arena data using
`python3 scripts/export_leaderboard.py` as before. These commands do not publish.

The six-topic collection in Arena’s shared Leaderboard / Problem views bypasses Arena's completeness filter, displays
one available model without comparative rankings, and never aggregates rubric scores
with pass rates. T3's mean includes only judged samples and flags incomplete scoring
coverage. Original T1 includes its undisclosed shots/optimizer_calls test limitation;
the corrected replay is a separate scoring variant.

The exporter verifies all topic summaries against sample statuses, execution outcomes,
unsupported imports, fingerprints and metrics, plus corrected replay slots and original
statuses. It does not execute candidates or call judges. Missing sample coverage remains
visible; incomplete tasks and infrastructure failures are excluded from pass estimates.
Generated preview JSON is retained locally; deployment automation is unchanged. Select QuantumBenchEval in Dataset; its T1–T6 Collection controls appear directly below Dataset. Old preview URLs redirect into Arena.

## Dataset reference pages

The Datasets navigation link opens an inventory table with problem counts and links
to six explanatory pages. Rebuild them with `python3 scripts/export_dataset_pages.py`;
counts come from local problem-content files and QuantumBenchEval task files.
