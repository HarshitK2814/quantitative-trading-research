"""Feature construction, and the single choke point for look-ahead protection.

The architectural rule
----------------------
Every feature in this project is built from a price panel by a **causal**
function -- one whose value at date *t* depends only on data at or before *t* --
and is then passed through :func:`make_tradable` exactly once before any
portfolio weight is derived from it.

That is the whole design. There is one shift, in one function, and
``tests/test_no_lookahead.py`` asserts mechanically that it works: perturb the
price panel strictly after date *t*, recompute, and every tradable feature
value up to *t* must be bit-identical.

Why a single choke point rather than shifting inside each feature: with N
feature functions each doing its own shifting, look-ahead safety becomes N
separate things to get right and to re-verify whenever a feature is added. With
one choke point it is a single invariant, and a new feature inherits it for free.

Why causality is not enough on its own
--------------------------------------
A rolling mean over a trailing window is causal -- it uses no future data. But a
signal computed from the *close* of day *t* still cannot be traded at that same
close: the number does not exist until the market has closed. Acting on it would
be a subtle but complete look-ahead violation, and it is the single most common
way a backtest silently overstates performance.

:func:`make_tradable` therefore shifts by one full bar, so a signal formed from
information through the close of day *t* first influences positions on day
*t+1*. The backtest then executes at day *t+1*'s open or close, adding a further
gap.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

#: Bars between a signal being observable and it being actionable. One full bar
#: is the minimum defensible value; the backtester adds execution delay on top.
DEFAULT_SIGNAL_LAG: int = 1


# ---------------------------------------------------------------------------
# The choke point
# ---------------------------------------------------------------------------


def make_tradable(
    features: pd.DataFrame | pd.Series, lag: int = DEFAULT_SIGNAL_LAG
) -> pd.DataFrame | pd.Series:
    """Shift a causal feature forward so it can only affect *later* positions.

    This is the **only** place in the project where a look-ahead shift is
    applied. Do not shift inside feature functions, and do not shift twice.

    Args:
        features: A causal feature panel or series, indexed by date.
        lag: Number of bars to shift forward. Must be >= 1; a lag of 0 would
            permit trading on a signal at the very bar that produced it.

    Returns:
        The same object shifted forward by ``lag`` bars. The first ``lag`` rows
        become NaN, since no tradable signal exists before the first signal has
        been observed.

    Raises:
        ValueError: If ``lag`` is less than 1.

    """
    if lag < 1:
        raise ValueError(
            f"lag must be >= 1 to prevent look-ahead; got {lag}. A signal formed "
            f"from the close of day t cannot be traded at that same close."
        )
    return features.shift(lag)


# ---------------------------------------------------------------------------
# Causal feature functions
#
# Every function below must depend only on data at or before each row's date.
# Adding a non-causal function here breaks the project's core guarantee, and
# tests/test_no_lookahead.py will fail if you do.
# ---------------------------------------------------------------------------


def total_return(
    prices: pd.DataFrame, lookback: int, skip: int = 0
) -> pd.DataFrame:
    """Trailing total return over ``lookback`` bars, optionally skipping recent ones.

    Args:
        prices: Adjusted price panel.
        lookback: Length of the formation window, in bars.
        skip: Bars to exclude at the recent end. The standard momentum
            specification skips the most recent month (~21 bars) because
            short-horizon reversal contaminates the signal -- last month's
            biggest winner tends to give some back.

    Returns:
        Return from ``t - lookback - skip`` to ``t - skip``, as a decimal.

    Raises:
        ValueError: If ``lookback`` is not positive or ``skip`` is negative.

    """
    if lookback <= 0:
        raise ValueError(f"lookback must be positive; got {lookback}")
    if skip < 0:
        raise ValueError(f"skip must be non-negative; got {skip}")

    recent = prices.shift(skip)
    older = prices.shift(skip + lookback)
    return recent / older - 1.0


def realised_volatility(
    prices: pd.DataFrame, window: int = 63, annualise: bool = True
) -> pd.DataFrame:
    """Trailing realised volatility of daily log returns.

    Log returns are used rather than simple returns because they aggregate
    additively over time, which is the property a volatility estimate needs.

    Args:
        prices: Adjusted price panel.
        window: Estimation window in bars. 63 ~ one quarter.
        annualise: Scale by sqrt(252).

    Returns:
        Rolling standard deviation, annualised if requested.

    """
    log_returns = np.log(prices / prices.shift(1))
    vol = log_returns.rolling(window, min_periods=window).std(ddof=1)
    if annualise:
        vol = vol * np.sqrt(252.0)
    return vol


def moving_average_ratio(prices: pd.DataFrame, window: int = 200) -> pd.DataFrame:
    """Ratio of price to its trailing moving average, minus one.

    A positive value means price is above its trend. Expressed as a ratio rather
    than a raw difference so it is comparable across assets at different price
    levels.

    Args:
        prices: Adjusted price panel.
        window: Moving-average window in bars.

    Returns:
        ``price / MA - 1``.

    """
    moving_average = prices.rolling(window, min_periods=window).mean()
    return prices / moving_average - 1.0


def cross_sectional_rank(features: pd.DataFrame) -> pd.DataFrame:
    """Rank each date's cross-section into [0, 1].

    Ranking is applied **within each date**, so it uses no information from
    other dates and is trivially causal. It makes the signal robust to outliers
    and comparable across volatility regimes.

    Args:
        features: A feature panel.

    Returns:
        Per-date percentile ranks. Dates with fewer than two valid observations
        yield NaN, since a rank across one asset is meaningless.

    """
    valid_counts = features.notna().sum(axis=1)
    ranks = features.rank(axis=1, pct=True, na_option="keep")
    return ranks.where(valid_counts >= 2)


def cross_sectional_zscore(features: pd.DataFrame) -> pd.DataFrame:
    """Standardise each date's cross-section to zero mean and unit variance.

    Args:
        features: A feature panel.

    Returns:
        Per-date z-scores. Dates with fewer than two valid observations, or with
        zero cross-sectional dispersion, yield NaN rather than a divide-by-zero
        artefact.

    """
    mean = features.mean(axis=1)
    std = features.std(axis=1, ddof=1)
    zscores = features.sub(mean, axis=0).div(std.replace(0.0, np.nan), axis=0)
    return zscores.where(features.notna().sum(axis=1) >= 2)


def build_feature_set(
    prices: pd.DataFrame,
    momentum_lookback: int = 126,
    momentum_skip: int = 21,
    vol_window: int = 63,
    trend_window: int = 200,
    lag: int = DEFAULT_SIGNAL_LAG,
) -> dict[str, pd.DataFrame]:
    """Build the standard tradable feature set in one call.

    Every feature returned has already passed through :func:`make_tradable`, so
    callers must **not** shift again.

    Args:
        prices: Adjusted price panel.
        momentum_lookback: Formation window for cross-sectional momentum.
        momentum_skip: Recent bars excluded from the momentum window.
        vol_window: Realised-volatility estimation window.
        trend_window: Moving-average window for the trend filter.
        lag: Bars between signal observation and tradability.

    Returns:
        Mapping of feature name to tradable panel. Keys: ``momentum``,
        ``momentum_rank``, ``volatility``, ``trend``.

    """
    momentum = total_return(prices, momentum_lookback, momentum_skip)
    features = {
        "momentum": momentum,
        "momentum_rank": cross_sectional_rank(momentum),
        "volatility": realised_volatility(prices, vol_window),
        "trend": moving_average_ratio(prices, trend_window),
    }
    return {name: make_tradable(panel, lag) for name, panel in features.items()}
