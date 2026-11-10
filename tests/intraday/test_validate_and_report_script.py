"""One-bar-lag proof for backtest_returns, and count_orders edge cases."""

from __future__ import annotations

import pandas as pd

from scripts.weekly_report import count_orders
from src.intraday.validate import backtest_returns


def test_signal_flip_earns_next_day_return_not_same_day():
    idx = pd.date_range("2026-01-01", periods=5)
    close = pd.DataFrame({"X": [100.0, 110.0, 121.0, 121.0, 121.0]}, index=idx)
    # signal flips to 1 on day index 1 (the +10% day) and stays on
    sig = lambda c: pd.Series([0.0, 1.0, 1.0, 1.0, 1.0], index=c.index)
    r = backtest_returns(close, sig, cost_bps=0.0)
    assert r.iloc[1] == 0.0                      # flip day: no return yet
    assert abs(r.iloc[2] - 0.10) < 1e-12         # earns day t+1 return
    assert r.iloc[3] == 0.0


def test_count_orders_missing_file(tmp_path):
    assert count_orders(tmp_path / "nope.csv") == 0


def test_count_orders_empty_file(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text("")
    assert count_orders(p) == 0


def test_count_orders_no_side_column(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text("a,b\n1,2\n")
    assert count_orders(p) == 0


def test_count_orders_counts_buy_sell_only(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text("side,qty\nbuy,1\nsell,2\nskip,0\n")
    assert count_orders(p) == 2
