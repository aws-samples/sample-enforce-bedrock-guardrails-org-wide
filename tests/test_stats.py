"""Unit tests for scripts/_lib/stats.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _lib.stats import percentile, summarize_latencies  # noqa: E402


class TestPercentile:
    def test_single_element(self) -> None:
        assert percentile([42.0], 50) == 42.0
        assert percentile([42.0], 99) == 42.0

    def test_known_quantiles(self) -> None:
        # 0..100 in 1.0 steps → 101 elements; p50 == 50.0, p99 == 99.0
        values = [float(i) for i in range(0, 101)]
        assert percentile(values, 0) == 0.0
        assert percentile(values, 50) == 50.0
        assert percentile(values, 99) == 99.0
        assert percentile(values, 100) == 100.0

    def test_interpolation(self) -> None:
        # Two values: the midpoint is the average.
        assert percentile([10.0, 20.0], 50) == 15.0
        # Three values: p50 is the middle exactly.
        assert percentile([10.0, 20.0, 30.0], 50) == 20.0

    def test_invalid_p(self) -> None:
        with pytest.raises(ValueError):
            percentile([1.0, 2.0], -1)
        with pytest.raises(ValueError):
            percentile([1.0, 2.0], 101)

    def test_empty(self) -> None:
        with pytest.raises(ValueError):
            percentile([], 50)


class TestSummarizeLatencies:
    def test_summary_keys(self) -> None:
        out = summarize_latencies([1.0, 2.0, 3.0, 4.0, 5.0])
        assert set(out.keys()) == {
            "count",
            "min_ms",
            "p50_ms",
            "p95_ms",
            "p99_ms",
            "max_ms",
            "mean_ms",
        }

    def test_summary_values(self) -> None:
        out = summarize_latencies([10.0, 20.0, 30.0, 40.0, 50.0])
        assert out["count"] == 5
        assert out["min_ms"] == 10.0
        assert out["max_ms"] == 50.0
        assert out["mean_ms"] == 30.0
        assert out["p50_ms"] == 30.0
