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


def equity_from_history(hist: dict) -> pd.Series:
    """Clean an Alpaca portfolio-history dict into a daily equity Series.

    Drops null and non-positive equity, keeps the last point per day.
    Raises ValueError if fewer than 2 usable points remain.
    """
    idx = pd.to_datetime(hist["timestamp"], unit="s").normalize()
    eq = pd.Series(hist["equity"], index=idx, dtype=float).dropna()
    eq = eq[eq > 0]
    eq = eq[~eq.index.duplicated(keep="last")]
    if len(eq) < 2:
        raise ValueError("not enough equity history")
    return eq


def render_report(stats: dict, first: str, last: str, n_trades: int) -> str:
    """Markdown body for the weekly report, with the real window stated."""
    return (
        f"# Session trader report, {first} to {last}\n\n"
        f"| Metric | Value |\n|---|---|\n"
        f"| Return (account) | {stats['return']:.2%} |\n"
        f"| Return (SPY buy-and-hold) | {stats['bench_return']:.2%} |\n"
        f"| Max drawdown | {stats['max_drawdown']:.2%} |\n"
        f"| Sharpe (annualised) | {stats['sharpe']:.2f} |\n"
        f"| Trading days used | {stats['days']} |\n"
        f"| Orders logged | {n_trades} |\n\n"
        "No profit claim is made. A record this short is mostly noise; "
        "judge by drawdown control and rule-following, not return.\n\n"
        "**Read with care:** under ~250 trading days a Sharpe ratio carries almost "
        "no information. Alpaca paper fills ignore slippage and market impact.\n"
    )
