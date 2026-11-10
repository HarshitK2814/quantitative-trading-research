"""Plain performance statistics for the weekly report."""

from __future__ import annotations

import numpy as np
import pandas as pd


def summarize(equity: pd.Series, bench: pd.Series) -> dict:
    """Return, drawdown and Sharpe for an equity curve vs a benchmark curve."""
    r = equity.pct_change().dropna()
    std = r.std()
    return {
        "return": float(equity.iloc[-1] / equity.iloc[0] - 1),
        "bench_return": float(bench.iloc[-1] / bench.iloc[0] - 1),
        "max_drawdown": float((equity / equity.cummax() - 1).min()),
        "sharpe": float(r.mean() / std * np.sqrt(252)) if std and std > 0 else 0.0,
        "days": int(len(equity)),
    }
