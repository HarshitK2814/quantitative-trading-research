import numpy as np
import pandas as pd

from src.search.ensemble import ensemble_weights, kill_scale, latest_target, to_alpaca
from src.search.engine import run_weights

IDX = pd.bdate_range("2023-01-01", periods=300)


def _setup(sig_lo=0.005, sig_hi=0.02, seed=3):
    rng = np.random.default_rng(seed)
    rets = pd.DataFrame({"SPY": rng.normal(0, sig_lo, 300), "QQQ": rng.normal(0, sig_hi, 300)}, index=IDX)
    close = 100 * (1 + rets).cumprod()
    bps = pd.Series(0.0, index=close.columns)
    w = {"lo": pd.DataFrame({"SPY": 1.0, "QQQ": 0.0}, index=IDX),
         "hi": pd.DataFrame({"SPY": 0.0, "QQQ": 1.0}, index=IDX)}
    r = {k: run_weights(v, close, bps=bps) for k, v in w.items()}
    return w, r, close, bps


def test_gross_never_exceeds_one():
    rng = np.random.default_rng(1)
    w, r, close, bps = _setup()
    w["lo"] = pd.DataFrame(rng.uniform(-1, 1, (300, 2)), index=IDX, columns=close.columns)
    r["lo"] = run_weights(w["lo"], close, bps=bps)
    ew = ensemble_weights(w, r, close, bps)
    assert (ew.abs().sum(axis=1) <= 1.0 + 1e-9).all()


def test_low_vol_sleeve_gets_more_weight():
    w, r, close, bps = _setup()
    ew = ensemble_weights(w, r, close, bps)
    last = ew.iloc[-1]
    assert last["SPY"] > last["QQQ"] > 0


def test_latest_target_clips():
    ew = pd.DataFrame({"A": [0.5], "B": [-0.4], "C": [0.05], "D": [0.0]})
    t = latest_target(ew, pos_cap=0.10)
    assert t["A"] == 0.10 and t["B"] == -0.10 and t["C"] == 0.05 and "D" not in t


def test_kill_switch_levels_and_latch():
    st = {}
    assert kill_scale(100.0, st) == 1.0
    assert kill_scale(89.0, st) == 0.5
    assert kill_scale(84.0, st) == 0.0
    assert kill_scale(120.0, st) == 0.0 and st["killed"]


def test_symbol_mapping():
    assert to_alpaca("BRK-B") == "BRK.B" and to_alpaca("BTC-USD") == "BTC/USD"


def test_zero_vol_sleeve_does_not_zero_the_mix():
    w, r, close, bps = _setup()
    r["lo"] = r["lo"] * 0.0
    ew = ensemble_weights(w, r, close, bps)
    assert np.isfinite(ew.values).all()
    assert ew.iloc[-50:].abs().sum(axis=1).max() > 0.1
