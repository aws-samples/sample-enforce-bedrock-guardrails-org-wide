"""Statistics helpers used by the benchmark output.

Pure functions. No I/O. Unit tested in tests/test_stats.py.
"""
from __future__ import annotations

import statistics
from typing import Iterable, Sequence


def percentile(sorted_values: Sequence[float], p: float) -> float:
    """Linearly-interpolated percentile over a pre-sorted sequence.

    Uses the AWS-CloudWatch-style interpolation (`p` in [0, 100]).
    Returns the only element when the sequence has length 1, raises
    ValueError on an empty sequence.
    """
    if not sorted_values:
        raise ValueError("percentile() over empty sequence")
    if not (0.0 <= p <= 100.0):
        raise ValueError(f"percentile p must be in [0, 100], got {p}")
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    k = (p / 100.0) * (n - 1)
    lo = int(k)
    hi = min(lo + 1, n - 1)
    frac = k - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def summarize_latencies(latencies_ms: Iterable[float]) -> dict[str, float]:
    """Summary stats for a benchmark scenario."""
    sorted_values = sorted(latencies_ms)
    return {
        "count": len(sorted_values),
        "min_ms": round(min(sorted_values), 2),
        "p50_ms": round(percentile(sorted_values, 50), 2),
        "p95_ms": round(percentile(sorted_values, 95), 2),
        "p99_ms": round(percentile(sorted_values, 99), 2),
        "max_ms": round(max(sorted_values), 2),
        "mean_ms": round(statistics.fmean(sorted_values), 2),
    }
