"""Round-2 weight transforms (H11, H13, H15), pre-registered in hypotheses.md.

Each function takes H1 target weights (already lagged, NaN on non-rebalance
dates) and returns new target weights on the same dates, so ``run_backtest``
is unchanged. Parameters have no defaults for the grid values on purpose: the
grid and primaries live in the pre-registration and the harness, not here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features import DEFAULT_SIGNAL_LAG, make_tradable


def apply_no_trade_band(
    targets: pd.DataFrame,
    prices: pd.DataFrame,
    rf_daily: pd.Series,
    band: float,
    phi: float,
) -> pd.DataFrame:
    """H11: no-trade band with partial adjustment.

    Trade only assets whose drifted weight is > ``band`` from target, and then
    close a fraction ``phi`` of the gap.

    Drift mirrors ``run_backtest`` (rebalance, apply the day's return, drift),
    so band=0, phi=1 reproduces the input exactly.
    """
    returns = prices.pct_change(fill_method=None).fillna(0.0).to_numpy()
    rf = rf_daily.reindex(prices.index).ffill().bfill().fillna(0.0).to_numpy()
    reb = targets.notna().any(axis=1).to_numpy()
    tgt_all = targets.to_numpy()
    out = targets.copy()
    held = np.zeros(targets.shape[1])

    for day in range(len(targets)):
        if reb[day]:
            tgt = np.nan_to_num(tgt_all[day], nan=0.0)
            gap = tgt - held
            new = held + phi * gap * (np.abs(gap) > band)
            new = np.clip(new, 0.0, None)
            total = new.sum()
            if total > 1.0:
                new = new / total
            out.iloc[day] = new
            held = new
        growth = 1.0 + float(held @ returns[day]) + (1.0 - held.sum()) * rf[day]
        if abs(growth) > 1e-12:
            held = held * (1.0 + returns[day]) / growth
    return out


def regime_state(
    spy: pd.Series,
    theta: float,
    window: int,
    vol_window: int = 63,
    lag: int = DEFAULT_SIGNAL_LAG,
) -> pd.Series:
    """H13 state: 1.0 if SPY vol > theta and trailing return < 0, else 0.0.

    NaN while either input is unavailable. Lagged once via ``make_tradable``.
    """
    vol = spy.pct_change(fill_method=None).rolling(
        vol_window, min_periods=vol_window
    ).std(ddof=1) * np.sqrt(252.0)
    trend = spy / spy.shift(window) - 1.0
    known = vol.notna() & trend.notna()
    state = ((vol > theta) & (trend < 0)).astype(float).where(known)
    return make_tradable(state, lag)


def apply_regime_scaling(
    weights: pd.DataFrame,
    spy: pd.Series,
    theta: float,
    scale: float,
    window: int,
    vol_window: int = 63,
    lag: int = DEFAULT_SIGNAL_LAG,
) -> pd.DataFrame:
    """H13: multiply all weights by ``scale`` while the stress state is ON.

    Unknown state counts as OFF (baseline weights).
    """
    state = regime_state(spy, theta, window, vol_window, lag)
    out = weights.copy()
    for when in weights.dropna(how="all").index:
        if state.get(when, np.nan) == 1.0:
            out.loc[when] = (weights.loc[when] * scale).to_numpy()
    return out


def apply_absolute_gate(
    weights: pd.DataFrame,
    prices: pd.DataFrame,
    rf_daily: pd.Series,
    gate_window: int,
    lag: int = DEFAULT_SIGNAL_LAG,
) -> pd.DataFrame:
    """H15: absolute-momentum gate with cash fallback.

    An asset keeps its weight only if its trailing return over
    ``gate_window`` exceeds the compounded risk-free return; else its
    weight goes to cash. Rows without a full window of history are NaN (no trade).
    """
    rf = rf_daily.reindex(prices.index).ffill().bfill().fillna(0.0)
    cum = (1.0 + rf).cumprod()
    rf_window = cum / cum.shift(gate_window) - 1.0
    asset_ret = prices / prices.shift(gate_window) - 1.0
    ok = make_tradable(
        asset_ret.sub(rf_window, axis=0).gt(0.0).astype(float).where(
            asset_ret.notna() & rf_window.notna().to_numpy()[:, None]
        ),
        lag,
    )
    out = weights.copy()
    for when in weights.dropna(how="all").index:
        flags = ok.loc[when]
        if flags.isna().any():
            out.loc[when] = np.nan
        else:
            out.loc[when] = (weights.loc[when] * flags).to_numpy()
    return out


def common_start(frames: list[pd.DataFrame]) -> pd.Timestamp:
    """Latest first non-NaN rebalance row across ``frames``."""
    firsts = [f.dropna(how="all").index.min() for f in frames]
    return max(firsts)
