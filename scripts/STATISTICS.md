# Leaderboard statistics

Run `python scripts/export_leaderboard.py` in an environment with NumPy installed.
The benchmark repository's `.venv/bin/python` has the required dependency.
The exporter recomputes pass@1/3/5 from five scored samples per task, then exports
10,000-replicate task-percentile 95% CIs and sample standard deviations (ddof=1).
Both dataset and category views show CI and SD (percentage points). Legacy
`data/results/confidence_intervals.json` is regenerated, not used as an input.
`leaderboard/statistics_manifest.json` records seed, method, versions and source hashes.

These intervals condition on recorded evaluation outcomes; they do not correct
infrastructure failures, measure independent generation reruns, or quantify judge
variation. Constant scores yield degenerate intervals; singleton categories have
no CI/SD. Intervals are pointwise, not simultaneous. Overall CIs are deliberately
omitted because benchmark suites overlap. The six-topic QuantumBenchEval collection
has separate scoring and is not changed by this original-collection analysis.

The benchmark notebook's final section exports current paired sign-flip tests
(global Holm correction) and bootstrap rank intervals to
`experiments/statistics/leaderboard_current/`. These use common task panels per
suite and average ranks for ties; no aggregate rank across suites is claimed.
