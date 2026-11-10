"""Tests for report statistics."""

from __future__ import annotations

import pandas as pd
import pytest

from src.intraday.report import summarize


def test_summarize_basic():
    idx = pd.date_range("2026-01-01", periods=4)
    eq = pd.Series([100.0, 110.0, 99.0, 105.0], index=idx)
    bench = pd.Series([100.0, 101.0, 102.0, 103.0], index=idx)
    s = summarize(eq, bench)
    assert s["return"] == pytest.approx(0.05)
    assert s["bench_return"] == pytest.approx(0.03)
    assert s["max_drawdown"] == pytest.approx(-0.10)
    assert s["days"] == 4
