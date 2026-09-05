"""Mechanical look-ahead tests.

This is the most load-bearing test file in the project. Every backtest result
is only as trustworthy as the guarantee asserted here.

The core idea -- the shift-invariance test -- is stronger than reading code and
convincing yourself it looks causal:

    Take a price panel. Compute features. Now go back and change the prices on
    every date strictly AFTER some cutoff date t, to arbitrary different values.
    Recompute. Every tradable feature value up to and including t must be
    bit-identical.

If a single feature reads even one bar into the future, the perturbation
propagates backwards across the cutoff and the assertion fails. This holds
regardless of how the feature is implemented, so it keeps working for features
that do not exist yet.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features import (
    DEFAULT_SIGNAL_LAG,
    build_feature_set,
    cross_sectional_rank,
    cross_sectional_zscore,
    make_tradable,
    moving_average_ratio,
    realised_volatility,
    total_return,
)


@pytest.fixture
def prices() -> pd.DataFrame:
    """A 600-bar, 5-ticker price panel with a fixed seed."""
    index = pd.bdate_range("2018-01-01", periods=600, name="date")
    rng = np.random.default_rng(20260905)
    return pd.DataFrame(
        {
            ticker: 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.011, len(index))))
            for ticker in ("AAA", "BBB", "CCC", "DDD", "EEE")
        },
        index=index,
    )


def _perturb_after(prices: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Replace every price strictly after ``cutoff`` with different values.

    The replacement is deliberately drastic -- a different random path at a
    different level -- so that any leakage across the cutoff is unmistakable
    rather than lost in floating-point noise.
    """
    perturbed = prices.copy()
    future = perturbed.index > cutoff
    rng = np.random.default_rng(999)
    perturbed.loc[future, :] = rng.uniform(
        10.0, 500.0, size=(int(future.sum()), prices.shape[1])
    )
    return perturbed


# ---------------------------------------------------------------------------
# The central invariant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cutoff_position", [250, 400, 550])
def test_feature_set_is_shift_invariant(
    prices: pd.DataFrame, cutoff_position: int
) -> None:
    """No tradable feature at or before t may depend on data after t.

    This is the project's central look-ahead guarantee. Run at three different
    cutoffs so a failure cannot hide at a single boundary.
    """
    cutoff = prices.index[cutoff_position]

    baseline = build_feature_set(prices)
    perturbed = build_feature_set(_perturb_after(prices, cutoff))

    assert set(baseline) == set(perturbed)

    for name in baseline:
        original = baseline[name].loc[:cutoff]
        recomputed = perturbed[name].loc[:cutoff]
        pd.testing.assert_frame_equal(
            original,
            recomputed,
            check_exact=True,
            obj=f"feature {name!r} up to {cutoff.date()}",
        )


@pytest.mark.parametrize(
    "feature_fn",
    [
        lambda p: total_return(p, 126, 21),
        lambda p: total_return(p, 21, 0),
        lambda p: realised_volatility(p, 63),
        lambda p: moving_average_ratio(p, 200),
        lambda p: cross_sectional_rank(total_return(p, 126, 21)),
        lambda p: cross_sectional_zscore(total_return(p, 126, 21)),
    ],
    ids=["mom_126_21", "mom_21_0", "vol_63", "trend_200", "rank", "zscore"],
)
def test_each_feature_function_is_causal(prices: pd.DataFrame, feature_fn) -> None:
    """Each raw feature function individually uses no future data.

    Tested separately from the bundled set so a failure names the culprit
    directly instead of pointing at ``build_feature_set``.
    """
    cutoff = prices.index[400]
    baseline = feature_fn(prices).loc[:cutoff]
    recomputed = feature_fn(_perturb_after(prices, cutoff)).loc[:cutoff]
    pd.testing.assert_frame_equal(baseline, recomputed, check_exact=True)


# ---------------------------------------------------------------------------
# The choke point itself
# ---------------------------------------------------------------------------


def test_make_tradable_shifts_forward_by_one_bar(prices: pd.DataFrame) -> None:
    """The value tradable on day t+1 is the value observed on day t."""
    feature = total_return(prices, 21)
    tradable = make_tradable(feature, lag=1)
    for position in (300, 450):
        assert tradable.iloc[position].equals(feature.iloc[position - 1])


def test_make_tradable_blanks_the_leading_rows(prices: pd.DataFrame) -> None:
    """No signal is tradable before one has been observed."""
    tradable = make_tradable(total_return(prices, 21), lag=DEFAULT_SIGNAL_LAG)
    assert tradable.iloc[:DEFAULT_SIGNAL_LAG].isna().all().all()


@pytest.mark.parametrize("bad_lag", [0, -1, -5])
def test_make_tradable_rejects_non_positive_lag(
    prices: pd.DataFrame, bad_lag: int
) -> None:
    """A lag of zero would allow trading on the bar that produced the signal."""
    with pytest.raises(ValueError, match="lag must be >= 1"):
        make_tradable(total_return(prices, 21), lag=bad_lag)


def test_lag_zero_would_actually_leak(prices: pd.DataFrame) -> None:
    """Demonstrate that the lag is doing real work, not decoration.

    With ``lag=0`` the value available on day t is the one computed from day t's
    own close -- information that does not exist until the market has closed.
    This test pins the distinction that :func:`make_tradable` exists to enforce.
    """
    feature = total_return(prices, 21)
    unlagged = feature  # what lag=0 would give
    lagged = make_tradable(feature, lag=1)

    position = 300
    assert unlagged.iloc[position].equals(feature.iloc[position])  # same-bar: leak
    assert lagged.iloc[position].equals(feature.iloc[position - 1])  # prior bar: safe
    assert not lagged.iloc[position].equals(unlagged.iloc[position])


# ---------------------------------------------------------------------------
# Feature correctness (a causal feature can still be wrong)
# ---------------------------------------------------------------------------


def test_total_return_matches_manual_calculation(prices: pd.DataFrame) -> None:
    """Verify the arithmetic against an explicit index lookup."""
    lookback, skip, position = 126, 21, 400
    result = total_return(prices, lookback, skip).iloc[position]["AAA"]
    expected = (
        prices["AAA"].iloc[position - skip]
        / prices["AAA"].iloc[position - skip - lookback]
        - 1.0
    )
    assert result == pytest.approx(expected)


def test_skip_actually_excludes_recent_bars(prices: pd.DataFrame) -> None:
    """A skip of 21 must not be equivalent to a skip of 0."""
    with_skip = total_return(prices, 126, 21)
    without_skip = total_return(prices, 126, 0)
    assert not with_skip.iloc[400].equals(without_skip.iloc[400])


def test_total_return_rejects_invalid_parameters(prices: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="lookback must be positive"):
        total_return(prices, 0)
    with pytest.raises(ValueError, match="skip must be non-negative"):
        total_return(prices, 126, -1)


def test_volatility_is_positive_and_annualised(prices: pd.DataFrame) -> None:
    daily = realised_volatility(prices, 63, annualise=False).dropna()
    annual = realised_volatility(prices, 63, annualise=True).dropna()
    assert (daily > 0).all().all()
    np.testing.assert_allclose(annual.to_numpy(), daily.to_numpy() * np.sqrt(252.0))


def test_volatility_requires_a_full_window(prices: pd.DataFrame) -> None:
    """A partial window would understate volatility on early dates."""
    vol = realised_volatility(prices, 63)
    assert vol.iloc[:63].isna().all().all()
    assert vol.iloc[63:].notna().all().all()


def test_cross_sectional_rank_is_bounded_and_ordered(prices: pd.DataFrame) -> None:
    momentum = total_return(prices, 126, 21)
    ranks = cross_sectional_rank(momentum)
    populated = ranks.dropna(how="all")
    assert populated.min().min() > 0.0
    assert populated.max().max() <= 1.0

    # Index by date, not position: the two frames must be aligned to compare.
    when = prices.index[400]
    assert ranks.loc[when].idxmax() == momentum.loc[when].idxmax()
    assert ranks.loc[when].idxmin() == momentum.loc[when].idxmin()


def test_cross_sectional_rank_needs_two_observations() -> None:
    """A rank across a single asset carries no information."""
    index = pd.bdate_range("2020-01-01", periods=3)
    sparse = pd.DataFrame(
        {"AAA": [1.0, 2.0, 3.0], "BBB": [np.nan, np.nan, 1.0]}, index=index
    )
    ranks = cross_sectional_rank(sparse)
    assert ranks.iloc[0].isna().all()
    assert ranks.iloc[2].notna().all()


def test_zscore_is_standardised(prices: pd.DataFrame) -> None:
    zscores = cross_sectional_zscore(total_return(prices, 126, 21)).dropna(how="all")
    np.testing.assert_allclose(zscores.mean(axis=1).to_numpy(), 0.0, atol=1e-12)
    np.testing.assert_allclose(zscores.std(axis=1, ddof=1).to_numpy(), 1.0, atol=1e-12)


def test_zscore_handles_zero_dispersion() -> None:
    """Identical values across the cross-section must not divide by zero."""
    index = pd.bdate_range("2020-01-01", periods=2)
    flat = pd.DataFrame({"AAA": [5.0, 5.0], "BBB": [5.0, 5.0]}, index=index)
    assert cross_sectional_zscore(flat).isna().all().all()


def test_build_feature_set_returns_already_lagged_panels(
    prices: pd.DataFrame,
) -> None:
    """Callers must not shift again; verify the bundle is pre-lagged."""
    built = build_feature_set(prices, lag=1)
    expected = total_return(prices, 126, 21).shift(1)
    pd.testing.assert_frame_equal(built["momentum"], expected, check_exact=True)


# ---------------------------------------------------------------------------
# Meta-tests: does the leak detector actually detect leaks?
#
# A look-ahead test that always passes is worse than no test, because it
# manufactures false confidence. These tests verify the detector has teeth by
# feeding it features that are known to be non-causal.
# ---------------------------------------------------------------------------


def _leaks(prices: pd.DataFrame, feature_fn, cutoff_position: int = 400) -> bool:
    """Return True if ``feature_fn`` reads data after the cutoff."""
    cutoff = prices.index[cutoff_position]
    baseline = feature_fn(prices).loc[:cutoff]
    recomputed = feature_fn(_perturb_after(prices, cutoff)).loc[:cutoff]
    try:
        pd.testing.assert_frame_equal(baseline, recomputed, check_exact=True)
    except AssertionError:
        return True
    return False


@pytest.mark.parametrize(
    "leaky_fn",
    [
        lambda p: p.rolling(51, center=True).mean(),
        lambda p: p.shift(-1),
        lambda p: p.shift(-5) / p - 1.0,
        lambda p: (p - p.mean()) / p.std(),
        lambda p: p.expanding().mean().iloc[::-1].expanding().mean().iloc[::-1],
    ],
    ids=[
        "centered_rolling_window",
        "negative_shift",
        "forward_return_label",
        "full_sample_zscore",
        "reversed_expanding_mean",
    ],
)
def test_detector_catches_known_leaks(prices: pd.DataFrame, leaky_fn) -> None:
    """Each deliberately non-causal feature must be flagged.

    These are the five most common ways look-ahead enters a research pipeline:
    a centered window, an explicit negative shift, a forward-looking label left
    in the feature set, normalising by full-sample statistics, and any reversed
    cumulative operation.
    """
    assert _leaks(prices, leaky_fn), "detector failed to catch a known leak"


def test_detector_catches_backfill_only_when_there_is_a_hole(
    prices: pd.DataFrame,
) -> None:
    """``bfill`` leaks only where a NaN gives it something to pull backwards.

    This documents a real property of the shift-invariance test: it detects
    leakage **conditional on there being a path for information to propagate**.
    On a hole-free panel ``bfill`` is a genuine no-op, so passing is correct
    rather than a blind spot -- but it means the detector's power depends on the
    fixture exercising the path. Panels fed to it should therefore include
    missing values where the real data might.
    """
    assert not _leaks(prices, lambda p: p.bfill())

    holed = prices.copy()
    holed.iloc[395:401, 0] = np.nan  # straddles the cutoff at position 400
    assert _leaks(holed, lambda p: p.bfill())
