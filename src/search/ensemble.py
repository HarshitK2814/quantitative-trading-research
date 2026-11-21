"""Inverse-vol ensemble of sleeves + account kill switch."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.search.engine import cap_gross, run_weights


def to_alpaca(sym: str) -> str:
    return sym.replace("-USD", "/USD") if sym.endswith("-USD") else sym.replace("-", ".")


def ensemble_weights(sleeve_w: dict, sleeve_r: dict, close: pd.DataFrame, bps: pd.Series,
                     vol_target: float = 0.10) -> pd.DataFrame:
    """Full-history ensemble weights: inverse-vol sleeve mix (63d, lagged), then scaled
    to vol_target using the mix's own trailing 63d vol, never above 100% gross."""
    names = list(sleeve_w)
    R = pd.DataFrame(sleeve_r)
    iv = 1 / R.rolling(63).std().clip(lower=0.003).shift(1)
    a = iv.div(iv.sum(axis=1), axis=0).fillna(0.0)
    cols = sorted(set().union(*[w.columns for w in sleeve_w.values()]))
    comb = sum(sleeve_w[k].reindex(columns=cols, fill_value=0.0).mul(a[k], axis=0) for k in names)
    base = run_weights(comb, close[cols], bps=bps[cols])
    g = comb.abs().sum(axis=1)
    vol = base.rolling(63).std() * np.sqrt(252)
    s = np.minimum(1 / g.replace(0, np.nan), vol_target / vol).fillna(0.0).clip(upper=4)
    s = s.where(g * s <= 1.0, 1 / g)
    return cap_gross(comb.mul(s, axis=0).fillna(0.0))


def latest_target(ens_w: pd.DataFrame, pos_cap: float = 0.10) -> pd.Series:
    t = ens_w.iloc[-1]
    t = t[t.abs() > 1e-6].clip(-pos_cap, pos_cap)
    return t


def kill_scale(equity: float, state: dict) -> float:
    state["peak"] = max(state.get("peak", 0.0), equity)
    dd = equity / state["peak"] - 1
    if state.get("killed") or dd <= -0.15:
        state["killed"] = True
        return 0.0
    return 0.5 if dd <= -0.10 else 1.0
