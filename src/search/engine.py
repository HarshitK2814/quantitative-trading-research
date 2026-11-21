"""Vectorised weights -> net daily returns. Weights at close t earn t+1."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.search.universe import CRYPTO, ETFS, LEVERAGE


@dataclass(frozen=True)
class Costs:
    bps: float = 10.0
    borrow_annual: float = 0.01
    delist_return: float = -0.30


def cost_table(columns) -> pd.Series:
    return pd.Series([5.0 if c in ETFS else 25.0 if c in CRYPTO else 10.0 for c in columns],
                     index=list(columns))


def cap_gross(w: pd.DataFrame, cap: float = 1.0) -> pd.DataFrame:
    lev = pd.Series({c: LEVERAGE.get(c, 1.0) for c in w.columns})
    gross = (w.abs() * lev).sum(axis=1)
    scale = (cap / gross).clip(upper=1.0).fillna(1.0)
    return w.mul(scale, axis=0)


def run_weights(w, close, costs=Costs(), bps=None) -> pd.Series:
    w = w.reindex(index=close.index, columns=close.columns).fillna(0.0)
    w = w.where(close.notna(), 0.0)
    r = close.pct_change(fill_method=None)
    end = close.index[-1]
    for col, lv in close.apply(pd.Series.last_valid_index).items():
        if lv is not None and (end - lv).days > 7:
            k = close.index.get_loc(lv)
            if k + 1 < len(close.index):
                r.iloc[k + 1, close.columns.get_loc(col)] = costs.delist_return
    r = r.fillna(0.0)
    held = w.shift(1).fillna(0.0)
    b = bps.reindex(close.columns).fillna(costs.bps) if bps is not None \
        else pd.Series(costs.bps, index=close.columns)
    trade = w.diff().abs()
    trade.iloc[0] = w.iloc[0].abs()
    cost = (trade * b / 1e4).sum(axis=1)
    borrow = held.clip(upper=0).abs().sum(axis=1) * costs.borrow_annual / 252
    return (held * r).sum(axis=1) - cost - borrow


def metrics(r: pd.Series) -> dict:
    r = r.dropna()
    sd = r.std()
    eq = (1 + r).cumprod()
    sd_ok = bool(sd > 0)
    return {"sharpe": float(r.mean() / sd * np.sqrt(252)) if sd_ok else 0.0,
            "sharpe_d": float(r.mean() / sd) if sd_ok else 0.0,
            "ret_ann": float(r.mean() * 252),
            "total": float(eq.iloc[-1] - 1) if len(r) else 0.0,
            "max_dd": float((eq / eq.cummax() - 1).min()) if len(r) else 0.0,
            "n": int(len(r))}
