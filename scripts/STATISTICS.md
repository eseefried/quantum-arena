# Precomputed statistics

Pages runs `python3 scripts/export_leaderboard.py` with the Python standard library only.
It does not install NumPy or compute bootstrap intervals.

After results change, run from the sibling benchmark repository:

```bash
.venv/bin/python scripts/compute_leaderboard_statistics.py --leaderboard ../quantum-leaderboard
```

This computes statistics locally and copies `data/statistics/original_collection.json`
and the legacy `data/results/confidence_intervals.json` into this repository.
Commit those files together with the results. Then run the exporter to generate the site.
The exporter validates exact source-file hashes, selected model/dataset coverage,
task-level data/metadata hash, task counts and point estimates. Stale bundles fail
with an instruction to recompute locally rather than publishing mismatched intervals.

Statistics: 10,000 task bootstrap replicates; percentile 95% CIs; sample SD across
tasks (ddof=1). Conditional on saved evaluations, not infrastructure-error repairs
or independent rerun validation. Singleton intervals unavailable; constant scores
can yield zero-width CIs. No Overall CI across overlapping suites. QuantumBenchEval
is separate and unchanged. Paired/rank analyses remain in the benchmark notebook.
