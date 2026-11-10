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


from src.intraday.report import equity_from_history, render_report  # noqa: E402

DAY = 86400


def test_equity_from_history_drops_zero_and_dupes():
    hist = {
        "timestamp": [0, DAY, 2 * DAY, 2 * DAY + 60, 3 * DAY],
        "equity": [0.0, 100.0, 101.0, 102.0, 103.0],
    }
    eq = equity_from_history(hist)
    assert (eq > 0).all()
    assert len(eq) == 3
    assert eq.iloc[1] == pytest.approx(102.0)  # same-day duplicate: last value kept
    assert eq.iloc[-1] == pytest.approx(103.0)


def test_equity_from_history_too_short_raises():
    with pytest.raises(ValueError, match="not enough equity history"):
        equity_from_history({"timestamp": [0, DAY], "equity": [0.0, 100.0]})


def test_render_report_honest_labels():
    stats = {"return": 0.05, "bench_return": 0.03, "max_drawdown": -0.1,
             "sharpe": 1.2, "days": 4}
    text = render_report(stats, "2026-01-01", "2026-01-04", 7)
    assert "week ending" not in text.lower()
    assert "2026-01-01" in text and "2026-01-04" in text
    assert "No profit claim is made." in text
    assert "slippage" in text.lower()
    assert "| Orders logged | 7 |" in text
