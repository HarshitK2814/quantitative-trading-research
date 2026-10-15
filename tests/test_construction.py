"""Tests for ERC/HRP construction."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.construction import apply_risk_construction, erc_weights, hrp_weights
from src.signals import cross_sectional_momentum


def test_erc_diagonal_is_inverse_vol():
    sig = np.array([0.1, 0.2, 0.4])
    w = erc_weights(np.diag(sig**2))
    expected = (1 / sig) / (1 / sig).sum()
    assert np.allclose(w, expected, atol=1e-6)


def test_erc_equal_risk_contributions():
    rng = np.random.default_rng(0)
    a = rng.normal(size=(6, 6))
    cov = a @ a.T + 0.5 * np.eye(6)
    w = erc_weights(cov)
    rc = w * (cov @ w)
    assert w.sum() == np.float64(1.0) or abs(w.sum() - 1) < 1e-9
    assert np.allclose(rc, rc.mean(), rtol=1e-4)


def test_hrp_basic():
    w = hrp_weights(np.diag([0.01, 0.04]))
    assert abs(w.sum() - 1) < 1e-12 and (w >= 0).all()
    assert np.allclose(w, [0.8, 0.2])
    rng = np.random.default_rng(3)
    a = rng.normal(size=(5, 5))
    w5 = hrp_weights(a @ a.T + np.eye(5))
    assert abs(w5.sum() - 1) < 1e-12 and (w5 >= 0).all()


def _panel():
    rng = np.random.default_rng(5)
    idx = pd.bdate_range("2014-01-01", periods=900)
    px = pd.DataFrame(
        100 * np.cumprod(1 + rng.normal(0.0004, 0.01, (900, 8)), axis=0),
        index=idx, columns=list("ABCDEFGH"))
    return px


def test_apply_invariants_and_no_lookahead():
    px = _panel()
    base = lambda p: cross_sectional_momentum(p, lookback=60, skip=10, top_k=5)  # noqa: E731
    for method in ("erc", "hrp"):
        out = apply_risk_construction(base(px), px, method, cov_window=252)
        v = out.dropna(how="all")
        assert len(v) > 10
        assert (v >= 0).all().all() and (v.max(axis=1) <= 0.25 + 1e-12).all()
        assert (v.sum(axis=1) <= 1 + 1e-9).all()
        sel = base(px).dropna(how="all")
        assert ((v > 0) <= (sel.loc[v.index] > 0)).all().all()

        cut = px.index[700]
        p2 = px.copy()
        p2.loc[p2.index > cut] *= np.random.default_rng(9).uniform(
            0.5, 1.5, p2.loc[p2.index > cut].shape)
        out2 = apply_risk_construction(base(p2), p2, method, cov_window=252)
        pd.testing.assert_frame_equal(out.loc[:cut], out2.loc[:cut])
