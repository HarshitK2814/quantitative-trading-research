import numpy as np
import pandas as pd
from src.search.families import Trial
from src.search.select import add_dsr, dedup, perturb, split_stats


def test_split_stats_keys():
    idx = pd.bdate_range("2019-01-01", "2025-06-30")
    r = pd.Series(np.random.default_rng(1).normal(0, .01, len(idx)), index=idx)
    s = split_stats(r)
    assert set(s) == {"train", "valid", "hold"} and s["valid"]["n"] > 900


def test_dsr_penalises_many_trials():
    t = pd.DataFrame({"valid_sharpe_d": [0.08] + [0.0] * 9, "valid_n": 1000,
                      "valid_skew": 0.0, "valid_kurt": 3.0})
    few = add_dsr(t.iloc[:2].copy())["dsr"].iloc[0]
    many = add_dsr(t.copy())["dsr"].iloc[0]
    assert many < few


def test_perturb_scales_numeric_params_only():
    t = Trial("x", "tsmom", {"universe": "s1", "lookback": 100, "long_short": True,
                             "vol_target": False})
    vals = sorted(p.params["lookback"] for p in perturb(t))
    assert vals == [80, 120]


def test_dedup_drops_correlated():
    a = pd.Series(np.random.default_rng(2).normal(size=300))
    out = dedup({"a": a, "b": a * 2, "c": -a.shift(1).fillna(0)}, ["a", "b", "c"])
    assert out == ["a", "c"]
