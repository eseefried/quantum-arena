"""Reproducible task-bootstrap statistics, conditional on saved scored samples.
Requires numpy. No cross-suite inference: suites contain overlapping tasks.
"""
import hashlib
import numpy as np

REPLICATES = 10000
SEED = 20260922

def summarize(rows, group_key):
    result = {}
    seed = int.from_bytes(hashlib.sha256((str(SEED) + repr(group_key)).encode()).digest()[:8], 'big')
    rng = np.random.default_rng(seed)
    for k in (1, 3, 5):
        key = f"pass_at_{k}"
        values = [r[key] for r in rows if r.get(key) is not None]
        x = np.asarray(values, dtype=float)
        n = len(x)
        result[key + "_n_tasks"] = n
        result[key + "_std"] = float(x.std(ddof=1)) if n > 1 else None
        result[key + "_constant_scores"] = bool(n and np.ptp(x) == 0)
        lo = hi = None
        if n > 1:
            draws = np.concatenate([x[rng.integers(n, size=(min(250, REPLICATES-i), n))].mean(axis=1)
                                    for i in range(0, REPLICATES, 250)])
            lo, hi = map(float, np.quantile(draws, [.025, .975]))
        result[key + "_ci_lo"] = lo
        result[key + "_ci_hi"] = hi
    return result
