"""Pre-registered signals. Parameters are fixed in research/hypotheses_sessions.md."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pandas as pd


def trend_signal(close: pd.Series, fast: int, slow: int) -> pd.Series:
    """1.0 when close > slow SMA and fast SMA > slow SMA, else 0.0."""
    f = close.rolling(fast).mean()
    s = close.rolling(slow).mean()
    return ((close > s) & (f > s)).astype(float)


def _rsi(close: pd.Series, n: int = 2) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn)).fillna(50.0)


def meanrev_signal(close: pd.Series) -> pd.Series:
    """Long when RSI(2)<10 and close>SMA200; exit when RSI(2)>70."""
    rsi = _rsi(close, 2).values
    sma = close.rolling(200).mean().values
    held, out = 0.0, []
    for c, r, s in zip(close.values, rsi, sma, strict=True):
        if held == 0.0 and r < 10.0 and c > s:   # NaN sma -> False
            held = 1.0
        elif held == 1.0 and r > 70.0:
            held = 0.0
        out.append(held)
    return pd.Series(out, index=close.index)


@dataclass(frozen=True)
class StrategySpec:
    """One pre-registered strategy."""

    id: str
    symbols: tuple[str, ...]
    asset_class: str  # "etf" | "stock" | "crypto"
    capital_fraction: float
    signal_fn: Callable[[pd.Series], pd.Series]
    active: bool = False  # flipped only after the gate passes (Task 7)


REGISTRY: dict[str, StrategySpec] = {
    "S1": StrategySpec(
        "S1", ("SPY", "QQQ", "XLK", "XLF", "XLE", "XLV"), "etf", 0.40,
        lambda c: trend_signal(c, 50, 200), True,
    ),
    "S2": StrategySpec(
        "S2", ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"), "stock", 0.30,
        meanrev_signal, True,
    ),
    "S3": StrategySpec(
        "S3", ("BTC/USD", "ETH/USD"), "crypto", 0.30,
        lambda c: trend_signal(c, 20, 100),
    ),
}


def completed_bars(close: pd.Series, today: date) -> pd.Series:
    """Drop any bar dated today (it is still forming), keeping the one-bar lag."""
    if len(close) and close.index[-1].date() >= today:
        return close[close.index.date < today]
    return close


def target_weights(
    registry: dict[str, StrategySpec], closes: dict[str, pd.Series]
) -> dict[str, float]:
    """Weight per symbol for active strategies; missing data means 0."""
    out: dict[str, float] = {}
    for spec in registry.values():
        if not spec.active:
            continue
        for sym in spec.symbols:
            c = closes.get(sym)
            if c is None or len(c) == 0:
                out[sym] = 0.0
                continue
            sig = float(spec.signal_fn(c).iloc[-1])
            out[sym] = sig * spec.capital_fraction / len(spec.symbols)
    return out
