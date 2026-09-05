"""Strategy signals: mapping features to target portfolio weights.

Each function here implements one of the pre-registered hypotheses in
``research/hypotheses.md``. **The default parameters are exactly the primary
specifications recorded there before any backtest was run**, and they must not
be edited to improve a result. Changing a default silently converts a
pre-registered test into a fitted one, and the git history of both files is
what makes that verifiable.

Look-ahead protection
---------------------
Every function here builds features from prices, passes them through
:func:`src.features.make_tradable` **exactly once**, and only then forms
weights. Target weights therefore inherit the one-bar lag, and the backtest
engine deliberately does not shift again -- so the shift lives in exactly one
place in the whole project.

Weight conventions
------------------
Returned frames are ``NaN`` on non-rebalance dates, which the engine reads as
"no trade today". On rebalance dates every asset has a weight, with zeros for
assets not held. Weights sum to at most 1.0; any remainder is cash.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from src.backtest import rebalance_schedule
from src.features import (
    DEFAULT_SIGNAL_LAG,
    make_tradable,
    realised_volatility,
    total_return,
)

logger = logging.getLogger(__name__)


def _blank_weights(index: pd.DatetimeIndex, assets) -> pd.DataFrame:
    """Build an all-NaN weight frame, meaning no rebalance on any date."""
    return pd.DataFrame(np.nan, index=index, columns=list(assets))


def _select_top_k(row: pd.Series, k: int) -> pd.Series:
    """Return equal weights on the k highest-scoring assets in one row.

    Ties are broken by the panel's column order, which is fixed *ex ante* in
    ``config.UNIVERSE``. Deterministic tie-breaking matters: a rule that broke
    ties by current return would leak the very thing being predicted.
    """
    valid = row.dropna()
    if len(valid) == 0:
        return pd.Series(0.0, index=row.index)
    chosen = valid.nlargest(min(k, len(valid))).index
    weights = pd.Series(0.0, index=row.index)
    weights.loc[chosen] = 1.0 / len(chosen)
    return weights


def cross_sectional_momentum(
    prices: pd.DataFrame,
    lookback: int = 126,
    skip: int = 21,
    top_k: int = 5,
    rebalance: str = "ME",
    lag: int = DEFAULT_SIGNAL_LAG,
) -> pd.DataFrame:
    """H1: hold the top-k assets by trailing return, equally weighted.

    Defaults are H1's pre-registered primary specification: 126-day formation,
    21-day skip, top 5, monthly rebalance.

    Args:
        prices: Adjusted close panel.
        lookback: Formation window in bars.
        skip: Recent bars excluded, to avoid short-horizon reversal.
        top_k: Number of assets held.
        rebalance: Pandas offset alias for the rebalance schedule.
        lag: Bars between signal observation and tradability.

    Returns:
        Target weights, NaN except on rebalance dates.

    """
    signal = make_tradable(total_return(prices, lookback, skip), lag)
    schedule = rebalance_schedule(prices.index, rebalance)

    weights = _blank_weights(prices.index, prices.columns)
    for when in schedule:
        row = signal.loc[when]
        if row.notna().sum() >= top_k:
            weights.loc[when] = _select_top_k(row, top_k).to_numpy()
    return weights


def time_series_trend(
    prices: pd.DataFrame,
    lookback: int = 252,
    rebalance: str = "ME",
    rf_daily: pd.Series | None = None,
    lag: int = DEFAULT_SIGNAL_LAG,
) -> pd.DataFrame:
    """H2: hold each asset only while its own trailing return beats cash.

    Unlike :func:`cross_sectional_momentum`, this can de-risk to cash entirely
    when nothing qualifies -- a structurally different mechanism, and the reason
    H2 is not merely H1 in another form.

    Args:
        prices: Adjusted close panel.
        lookback: Trailing window used to judge the trend.
        rebalance: Pandas offset alias.
        rf_daily: Daily risk-free rate. When supplied, an asset must beat the
            compounded risk-free return over the same window rather than merely
            being positive -- the correct comparison, and a stricter one when
            rates are high.
        lag: Signal lag in bars.

    Returns:
        Target weights, equally weighted across qualifying assets, NaN except on
        rebalance dates. Unallocated capital is held as cash.

    """
    signal = make_tradable(total_return(prices, lookback), lag)

    if rf_daily is not None:
        rf = rf_daily.reindex(prices.index).ffill().bfill().fillna(0.0)
        hurdle = make_tradable(
            (1.0 + rf).rolling(lookback).apply(np.prod, raw=True) - 1.0, lag
        )
    else:
        hurdle = pd.Series(0.0, index=prices.index)

    schedule = rebalance_schedule(prices.index, rebalance)
    weights = _blank_weights(prices.index, prices.columns)

    for when in schedule:
        row = signal.loc[when]
        threshold = float(hurdle.loc[when]) if not pd.isna(hurdle.loc[when]) else 0.0
        qualifying = row[row > threshold].dropna().index

        allocation = pd.Series(0.0, index=prices.columns)
        if len(qualifying) > 0:
            # Divide by the FULL universe size, not the qualifying count, so
            # that de-risking actually reduces exposure. Dividing by the
            # qualifying count would keep the book fully invested even when
            # only one asset passed the filter, which defeats the purpose.
            allocation.loc[qualifying] = 1.0 / len(prices.columns)
        weights.loc[when] = allocation.to_numpy()

    return weights


def short_term_reversal(
    prices: pd.DataFrame,
    lookback: int = 5,
    bottom_k: int = 5,
    rebalance: str = "W-FRI",
    lag: int = DEFAULT_SIGNAL_LAG,
) -> pd.DataFrame:
    """H3: hold the k worst recent performers, rebalanced weekly.

    Pre-registered with an explicit prediction of **failure**: the proposed
    mechanism is compensation for providing liquidity, and on the most liquid
    ETFs in the world that compensation should be near zero while turnover is
    high. Included precisely because it tests the opposite direction to H1 and
    H2.

    Args:
        prices: Adjusted close panel.
        lookback: Short formation window in bars.
        bottom_k: Number of losers held.
        rebalance: Pandas offset alias; weekly by default.
        lag: Signal lag in bars.

    Returns:
        Target weights, NaN except on rebalance dates.

    """
    signal = make_tradable(total_return(prices, lookback), lag)
    schedule = rebalance_schedule(prices.index, rebalance)

    weights = _blank_weights(prices.index, prices.columns)
    for when in schedule:
        row = signal.loc[when]
        if row.notna().sum() >= bottom_k:
            # Negate to reuse top-k selection: the worst performers rank highest.
            weights.loc[when] = _select_top_k(-row, bottom_k).to_numpy()
    return weights


def apply_inverse_volatility(
    weights: pd.DataFrame,
    prices: pd.DataFrame,
    vol_window: int = 63,
    max_weight: float = 0.25,
    lag: int = DEFAULT_SIGNAL_LAG,
) -> pd.DataFrame:
    """H4: re-weight a selection inversely to each asset's volatility.

    This is a *construction layer*, applied on top of whichever signal selects
    the assets -- it changes how much of each is held, never which are held.
    Separating selection from sizing is what lets H4 ask whether portfolio
    construction contributes more reliably than signal tuning.

    Args:
        weights: Target weights from a signal function.
        prices: Adjusted close panel.
        vol_window: Realised-volatility estimation window.
        max_weight: Per-asset cap applied after normalisation.
        lag: Signal lag in bars.

    Returns:
        Re-weighted targets, on the same rebalance dates, summing to at most 1.

    """
    volatility = make_tradable(realised_volatility(prices, vol_window), lag)
    result = weights.copy()

    for when in weights.dropna(how="all").index:
        selected = weights.loc[when]
        held = selected[selected > 0].index
        if len(held) == 0:
            continue

        vols = volatility.loc[when, held]
        if vols.isna().any() or (vols <= 0).any():
            continue  # keep the original equal weights rather than guess

        inverse = 1.0 / vols
        allocation = inverse / inverse.sum()
        allocation = allocation.clip(upper=max_weight)

        # Renormalise only if capping left us under-invested and headroom
        # remains; never scale above the original gross exposure.
        total = allocation.sum()
        if total > 0:
            allocation = allocation * min(1.0, selected.sum() / total)

        new_row = pd.Series(0.0, index=weights.columns)
        new_row.loc[held] = allocation
        result.loc[when] = new_row.to_numpy()

    return result


def apply_volatility_target(
    weights: pd.DataFrame,
    portfolio_returns: pd.Series,
    target_vol: float = 0.10,
    vol_window: int = 63,
    max_gross: float = 1.0,
) -> pd.DataFrame:
    """H4: scale gross exposure toward a target portfolio volatility.

    Warning:
        ``portfolio_returns`` must be the returns of an **already-run** backtest
        of the same unscaled weights, and is used only through a trailing
        window. Passing returns that postdate a rebalance date would be a
        look-ahead violation that the feature-level tests cannot catch, because
        it happens at the portfolio level. The trailing estimate is shifted by
        one bar here for that reason.

    Args:
        weights: Unscaled target weights.
        portfolio_returns: Daily returns of the unscaled portfolio.
        target_vol: Desired annualised volatility.
        vol_window: Trailing estimation window.
        max_gross: Cap on gross exposure. Defaults to 1.0 (no leverage).

    Returns:
        Scaled weights, never exceeding ``max_gross`` in total.

    """
    realised = (
        portfolio_returns.rolling(vol_window, min_periods=vol_window).std(ddof=1)
        * np.sqrt(252.0)
    ).shift(1)  # trailing only: the estimate must predate the rebalance

    result = weights.copy()
    for when in weights.dropna(how="all").index:
        current = realised.get(when, np.nan)
        if pd.isna(current) or current <= 0:
            continue
        scale = min(target_vol / float(current), max_gross)
        result.loc[when] = (weights.loc[when] * scale).to_numpy()
    return result
