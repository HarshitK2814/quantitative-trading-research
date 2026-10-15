"""Tests for H11/H13/H15 transforms, including shift-invariance."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.backtest import run_backtest
from src.round2 import (
    apply_absolute_gate,
    apply_no_trade_band,
    apply_regime_scaling,
    common_start,
)
from src.signals import cross_sectional_momentum


@pytest.fixture
def panel():
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2015-01-01", periods=900)
    rets = rng.normal(0.0004, 0.012, (900, 8))
    px = pd.DataFrame(100 * np.cumprod(1 + rets, axis=0), index=idx,
                      columns=list("ABCDEFGH"))
    rf = pd.Series(0.00005, index=idx)
    return px, rf


def _base(px):
    return cross_sectional_momentum(px, lookback=60, skip=10, top_k=3)


def test_band_zero_reproduces_baseline(panel):
    px, rf = panel
    w = _base(px)
    a = run_backtest(px, w, cost_bps=10, rf_daily=rf).returns
    b = run_backtest(px, apply_no_trade_band(w, px, rf, 0.0, 1.0),
                     cost_bps=10, rf_daily=rf).returns
    assert np.allclose(a, b, atol=1e-12)


def test_band_cuts_turnover_and_keeps_invariants(panel):
    px, rf = panel
    w = _base(px)
    base = run_backtest(px, w, cost_bps=10, rf_daily=rf)
    banded_w = apply_no_trade_band(w, px, rf, 0.10, 1.0)
    banded = run_backtest(px, banded_w, cost_bps=10, rf_daily=rf)
    assert banded.turnover.sum() < base.turnover.sum()
    v = banded_w.dropna(how="all")
    assert (v >= -1e-12).all().all() and (v.sum(axis=1) <= 1 + 1e-9).all()
    assert banded_w.notna().any(axis=1).equals(w.notna().any(axis=1))


def _shift_invariant(fn, px, cut):
    p2 = px.copy()
    rng = np.random.default_rng(1)
    p2.loc[p2.index > cut] *= rng.uniform(0.5, 1.5, p2.loc[p2.index > cut].shape)
    a, b = fn(px), fn(p2)
    pd.testing.assert_frame_equal(a.loc[:cut], b.loc[:cut])


def test_band_shift_invariant(panel):
    px, rf = panel
    cut = px.index[600]
    _shift_invariant(
        lambda p: apply_no_trade_band(_base(p), p, rf, 0.04, 0.75), px, cut)


def test_regime_scaling_and_invariance(panel):
    px, rf = panel
    spy = px["A"]
    w = _base(px)
    out = apply_regime_scaling(w, spy, theta=0.0, scale=0.5, window=60)
    rows = w.dropna(how="all").index
    for when in rows:
        ratio = out.loc[when].sum() / w.loc[when].sum()
        assert ratio == pytest.approx(0.5) or ratio == pytest.approx(1.0)
    # theta huge => never ON => identical
    off = apply_regime_scaling(w, spy, theta=10.0, scale=0.5, window=60)
    pd.testing.assert_frame_equal(off, w)
    cut = px.index[600]
    _shift_invariant(
        lambda p: apply_regime_scaling(_base(p), p["A"], 0.0, 0.5, 60), px, cut)


def test_gate_zeroes_losers_to_cash(panel):
    px, rf = panel
    px = px.copy()
    px["A"] = np.linspace(200, 50, len(px))  # persistent loser
    px["B"] = np.linspace(50, 400, len(px))  # persistent winner
    w = pd.DataFrame(np.nan, index=px.index, columns=px.columns)
    when = px.index[400]
    w.loc[when] = 0.0
    w.loc[when, ["A", "B"]] = 0.5
    out = apply_absolute_gate(w, px, rf, gate_window=100)
    assert out.loc[when, "A"] == 0.0
    assert out.loc[when, "B"] == 0.5


def test_gate_nan_without_history(panel):
    px, rf = panel
    w = pd.DataFrame(np.nan, index=px.index, columns=px.columns)
    w.iloc[50] = 0.125
    out = apply_absolute_gate(w, px, rf, gate_window=200)
    assert out.iloc[50].isna().all()


def test_gate_shift_invariant(panel):
    px, rf = panel
    cut = px.index[600]
    _shift_invariant(
        lambda p: apply_absolute_gate(_base(p), p, rf, 120), px, cut)


def test_common_start():
    idx = pd.bdate_range("2020-01-01", periods=10)
    a = pd.DataFrame(np.nan, index=idx, columns=["x"])
    b = a.copy()
    a.iloc[2] = 1.0
    b.iloc[5] = 1.0
    assert common_start([a, b]) == idx[5]
