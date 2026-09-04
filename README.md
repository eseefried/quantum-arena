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
