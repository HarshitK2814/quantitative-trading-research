"""Tests for session strategies and the validation gate."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from src.intraday.strategies import (
    REGISTRY,
    StrategySpec,
    completed_bars,
    meanrev_signal,
    target_weights,
    trend_signal,
)
from src.intraday.validate import backtest_returns, gate


def _series(values, start="2020-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values)))


def test_trend_long_in_uptrend_flat_in_downtrend():
    up = _series(np.linspace(100, 300, 300))
    down = _series(np.linspace(300, 100, 300))
    assert trend_signal(up, 50, 200).iloc[-1] == 1.0
    assert trend_signal(down, 50, 200).iloc[-1] == 0.0


def test_trend_flat_during_warmup():
    assert trend_signal(_series(np.linspace(1, 2, 100)), 50, 200).sum() == 0.0


def test_meanrev_enters_on_dip_in_uptrend_and_exits_on_bounce():
    base = list(np.linspace(100, 200, 250))
    dip = base + [190.0, 180.0]          # sharp drop, still above SMA200
    assert meanrev_signal(_series(dip)).iloc[-1] == 1.0
    bounce = dip + [195.0, 205.0, 215.0]
    assert meanrev_signal(_series(bounce)).iloc[-1] == 0.0


def test_completed_bars_drops_todays_bar():
    s = _series([1.0, 2.0, 3.0], start="2026-11-08")  # 8,9,10 Nov
    assert len(completed_bars(s, date(2026, 11, 10))) == 2
    assert len(completed_bars(s, date(2026, 11, 11))) == 3


def test_target_weights_only_active_and_split_equally():
    up = _series(np.linspace(100, 300, 300))
    spec_on = StrategySpec("T1", ("A", "B"), "etf", 0.4,
                           lambda c: trend_signal(c, 50, 200), True)
    spec_off = StrategySpec("T2", ("C",), "stock", 0.3,
                            lambda c: trend_signal(c, 50, 200), False)
    w = target_weights({"T1": spec_on, "T2": spec_off},
                       {"A": up, "B": up, "C": up})
    assert w == {"A": 0.2, "B": 0.2}


def test_target_weights_missing_data_is_omitted():
    spec = StrategySpec("T1", ("A",), "etf", 0.4,
                        lambda c: trend_signal(c, 50, 200), True)
    assert "A" not in target_weights({"T1": spec}, {})
    assert "A" not in target_weights({"T1": spec}, {"A": pd.Series(dtype=float)})


def test_target_weights_stale_or_nan_signal_is_omitted():
    from datetime import date
    spec = StrategySpec("T1", ("A", "B"), "etf", 0.4,
                        lambda c: trend_signal(c, 50, 200), True)
    idx = pd.date_range(end="2026-11-05", periods=300)
    ok = pd.Series(range(300), index=idx, dtype=float)
    w = target_weights({"T1": spec}, {"A": ok, "B": ok}, as_of=date(2026, 11, 9))
    assert set(w) == {"A", "B"}                      # 4 days old is fine
    w = target_weights({"T1": spec}, {"A": ok, "B": ok}, as_of=date(2026, 11, 10))
    assert w == {}                                   # 5 days old is stale
    short = pd.Series(range(10), index=idx[-10:], dtype=float)
    nan_spec = StrategySpec("T2", ("C",), "etf", 0.4,
                            lambda c: c.rolling(50).mean(), True)
    assert target_weights({"T2": nan_spec}, {"C": short}) == {}


def test_registry_symbols_are_disjoint_and_fractions_fit():
    syms = [s for spec in REGISTRY.values() for s in spec.symbols]
    assert len(syms) == len(set(syms))
    assert sum(s.capital_fraction for s in REGISTRY.values()) <= 1.0


def test_backtest_uses_one_bar_lag_and_gate_thresholds():
    closes = pd.DataFrame({"A": np.linspace(100, 400, 1500)},
                          index=pd.date_range("2019-01-01", periods=1500))
    rets = backtest_returns(closes, lambda c: trend_signal(c, 50, 200))
    assert rets.iloc[:200].abs().sum() == 0.0   # flat during warmup
    g = gate(rets, start="2021-01-01")
    assert g["passed"] is True and g["sharpe"] > 0.5
    losing = pd.Series(-0.01, index=closes.index)
    assert gate(losing, start="2021-01-01")["passed"] is False
