"""Backtest and the pre-registered pass/fail gate."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

SHARPE_MIN = 0.5
MAX_DD_FLOOR = -0.25


def backtest_returns(
    closes: pd.DataFrame,
    signal_fn: Callable[[pd.Series], pd.Series],
    cost_bps: float = 5.0,
) -> pd.Series:
    """Equal-weight daily returns across columns, signal lagged one bar."""
    per_asset = []
    for col in closes.columns:
        c = closes[col].dropna()
        pos = signal_fn(c).shift(1).fillna(0.0)
        gross = pos * c.pct_change().fillna(0.0)
        cost = pos.diff().abs().fillna(0.0) * cost_bps / 1e4
        per_asset.append(gross - cost)
    return pd.concat(per_asset, axis=1).mean(axis=1)


def gate(returns: pd.Series, start: str = "2021-01-01") -> dict:
    """Apply the pre-registered thresholds on the held-out window."""
    r = returns[returns.index >= pd.Timestamp(start)]
    std = r.std()
    sharpe = float(r.mean() / std * np.sqrt(252)) if std > 0 else 0.0
    equity = (1 + r).cumprod()
    max_dd = float((equity / equity.cummax() - 1).min()) if len(r) else 0.0
    passed = sharpe >= SHARPE_MIN and max_dd >= MAX_DD_FLOOR
    return {"sharpe": sharpe, "max_drawdown": max_dd, "passed": bool(passed),
            "days": int(len(r))}
