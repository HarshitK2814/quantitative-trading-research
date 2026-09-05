"""Tests for performance metrics.

Checked against closed-form answers wherever one exists. A metric that agrees
with itself across releases but disagrees with arithmetic is not much use.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.metrics import (
    annualised_return,
    annualised_turnover,
    annualised_volatility,
    beta_alpha,
    bootstrap_sharpe_ci,
    calmar_ratio,
    drawdown_details,
    drawdown_series,
    equity_curve,
    hit_rate,
    max_drawdown,
    newey_west_tstat,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    summarise,
    to_excess,
    total_return,
)


@pytest.fixture
def constant_returns() -> pd.Series:
    """Exactly +0.1% every day for one trading year."""
    index = pd.bdate_range("2020-01-01", periods=252, name="date")
    return pd.Series(0.001, index=index)


@pytest.fixture
def random_returns() -> pd.Series:
    """Four years of pseudo-random daily returns with a fixed seed."""
    index = pd.bdate_range("2018-01-01", periods=1008, name="date")
    rng = np.random.default_rng(20260905)
    return pd.Series(rng.normal(0.0004, 0.011, len(index)), index=index)


# ---------------------------------------------------------------------------
# Closed-form checks
# ---------------------------------------------------------------------------


def test_total_return_compounds(constant_returns: pd.Series) -> None:
    assert total_return(constant_returns) == pytest.approx(1.001**252 - 1)


def test_annualised_return_is_geometric(constant_returns: pd.Series) -> None:
    """252 days of +0.1% annualises to exactly 1.001**252 - 1."""
    assert annualised_return(constant_returns) == pytest.approx(1.001**252 - 1)


def test_geometric_beats_naive_arithmetic_annualisation() -> None:
    """The arithmetic shortcut overstates growth when returns are volatile.

    This is why annualised_return compounds rather than multiplying the mean
    by 252 -- and the gap widens with volatility, which is exactly when a
    strategy most wants to look good.
    """
    index = pd.bdate_range("2020-01-01", periods=252, name="date")
    volatile = pd.Series([0.10, -0.09] * 126, index=index)
    naive = volatile.mean() * 252
    assert annualised_return(volatile) < naive


def test_zero_volatility_gives_zero_annualised_vol(
    constant_returns: pd.Series,
) -> None:
    assert annualised_volatility(constant_returns) == pytest.approx(0.0, abs=1e-12)


def test_annualised_volatility_scales_by_root_252() -> None:
    index = pd.bdate_range("2020-01-01", periods=252, name="date")
    returns = pd.Series([0.01, -0.01] * 126, index=index)
    assert annualised_volatility(returns) == pytest.approx(
        returns.std(ddof=1) * np.sqrt(252)
    )


def test_sharpe_matches_manual_formula(random_returns: pd.Series) -> None:
    expected = (
        random_returns.mean() / random_returns.std(ddof=1) * np.sqrt(252)
    )
    assert sharpe_ratio(random_returns) == pytest.approx(expected)


def test_sharpe_is_nan_without_volatility(constant_returns: pd.Series) -> None:
    """A constant series has no risk, so a risk-adjusted ratio is undefined."""
    assert np.isnan(sharpe_ratio(constant_returns))


def test_excess_sharpe_is_lower_when_rf_is_positive(
    random_returns: pd.Series,
) -> None:
    """Subtracting a positive risk-free rate must reduce the Sharpe ratio."""
    raw = sharpe_ratio(random_returns, rf=None)
    excess = sharpe_ratio(random_returns, rf=0.0002)
    assert excess < raw


def test_to_excess_accepts_series_and_scalar(random_returns: pd.Series) -> None:
    rf_series = pd.Series(0.0001, index=random_returns.index)
    pd.testing.assert_series_equal(
        to_excess(random_returns, rf_series),
        to_excess(random_returns, 0.0001),
        check_names=False,
    )
    pd.testing.assert_series_equal(
        to_excess(random_returns, None), random_returns
    )


def test_sortino_exceeds_sharpe_for_right_skewed_returns() -> None:
    """Sortino ignores upside volatility, so it must be kinder here."""
    index = pd.bdate_range("2020-01-01", periods=252, name="date")
    # Many small losses, occasional large gains: upside dominates the variance.
    values = np.array([-0.001] * 240 + [0.05] * 12)
    returns = pd.Series(values, index=index)
    assert sortino_ratio(returns) > sharpe_ratio(returns)


def test_sortino_divides_by_all_observations() -> None:
    """Downside deviation uses the full sample with upside clipped to zero.

    Averaging only the negative days would divide by a smaller count and
    inflate the ratio. This pins the convention.
    """
    index = pd.bdate_range("2020-01-01", periods=4, name="date")
    returns = pd.Series([0.02, -0.01, 0.03, -0.02], index=index)
    downside = np.sqrt((np.array([0.0, -0.01, 0.0, -0.02]) ** 2).mean())
    expected = returns.mean() / downside * np.sqrt(252)
    assert sortino_ratio(returns) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Drawdown
# ---------------------------------------------------------------------------


def test_max_drawdown_of_a_known_path() -> None:
    """A path rising to 1.20 then falling to 0.96 is exactly -20%."""
    index = pd.bdate_range("2020-01-01", periods=4, name="date")
    returns = pd.Series([0.0, 0.20, -0.20, 0.0], index=index)
    curve = equity_curve(returns)
    assert curve.iloc[1] == pytest.approx(1.20)
    assert curve.iloc[2] == pytest.approx(0.96)
    assert max_drawdown(returns) == pytest.approx(-0.20)


def test_drawdown_is_never_positive(random_returns: pd.Series) -> None:
    assert (drawdown_series(random_returns) <= 1e-12).all()


def test_monotonic_growth_has_no_drawdown(constant_returns: pd.Series) -> None:
    assert max_drawdown(constant_returns) == pytest.approx(0.0, abs=1e-12)


def test_drawdown_details_locates_peak_and_trough() -> None:
    index = pd.bdate_range("2020-01-01", periods=6, name="date")
    returns = pd.Series([0.0, 0.20, -0.20, -0.10, 0.50, 0.0], index=index)
    details = drawdown_details(returns)
    assert details["peak_date"] == index[1]
    assert details["trough_date"] == index[3]
    assert details["days_peak_to_trough"] == 2
    assert details["recovery_date"] is not None


def test_drawdown_details_reports_no_recovery() -> None:
    """A series that never regains its peak must not claim a recovery date."""
    index = pd.bdate_range("2020-01-01", periods=4, name="date")
    returns = pd.Series([0.0, 0.20, -0.50, 0.0], index=index)
    details = drawdown_details(returns)
    assert details["recovery_date"] is None
    assert np.isnan(details["days_trough_to_recovery"])


def test_calmar_is_return_over_drawdown(random_returns: pd.Series) -> None:
    expected = annualised_return(random_returns) / abs(max_drawdown(random_returns))
    assert calmar_ratio(random_returns) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Trade statistics
# ---------------------------------------------------------------------------


def test_hit_rate_counts_strictly_positive_days() -> None:
    index = pd.bdate_range("2020-01-01", periods=4, name="date")
    returns = pd.Series([0.01, -0.01, 0.0, 0.02], index=index)
    assert hit_rate(returns) == pytest.approx(0.5)  # zero does not count as a win


def test_profit_factor_of_a_known_series() -> None:
    index = pd.bdate_range("2020-01-01", periods=4, name="date")
    returns = pd.Series([0.03, -0.01, 0.01, -0.01], index=index)
    assert profit_factor(returns) == pytest.approx(0.04 / 0.02)


def test_high_hit_rate_can_still_lose_money() -> None:
    """Hit rate alone is nearly uninformative -- this demonstrates why."""
    index = pd.bdate_range("2020-01-01", periods=100, name="date")
    returns = pd.Series([0.001] * 90 + [-0.02] * 10, index=index)
    assert hit_rate(returns) == pytest.approx(0.90)
    assert total_return(returns) < 0
    assert profit_factor(returns) < 1.0


def test_annualised_turnover_with_explicit_day_count() -> None:
    """12 monthly rebalances of 0.5 across one trading year is 6.0/year."""
    index = pd.bdate_range("2020-01-01", periods=12, freq="ME", name="date")
    turnover = pd.Series(0.5, index=index)
    assert annualised_turnover(turnover, n_trading_days=252) == pytest.approx(6.0)


def test_annualised_turnover_infers_span_when_day_count_absent() -> None:
    """Falling back to the index span must land near the exact answer."""
    index = pd.bdate_range("2020-01-01", periods=12, freq="ME", name="date")
    turnover = pd.Series(0.5, index=index)
    assert annualised_turnover(turnover) == pytest.approx(6.0, rel=0.05)


def test_annualised_turnover_does_not_scale_by_observation_count() -> None:
    """Regression test.

    An earlier version divided by the number of turnover observations, treating
    12 monthly rebalances as 12 consecutive days and inflating the result by
    roughly 21x. Turnover is sparse; elapsed time is what annualises it.
    """
    index = pd.bdate_range("2020-01-01", periods=12, freq="ME", name="date")
    turnover = pd.Series(0.5, index=index)
    assert annualised_turnover(turnover, n_trading_days=252) < 10.0


def test_more_frequent_rebalancing_raises_annual_turnover() -> None:
    """Weekly trading of the same size must annualise higher than monthly."""
    monthly = pd.Series(0.5, index=pd.bdate_range("2020-01-01", periods=12, freq="ME"))
    weekly = pd.Series(0.5, index=pd.bdate_range("2020-01-01", periods=52, freq="W-FRI"))
    assert annualised_turnover(weekly, 252) > annualised_turnover(monthly, 252)


# ---------------------------------------------------------------------------
# Benchmark-relative
# ---------------------------------------------------------------------------


def test_beta_of_an_asset_against_itself_is_one(random_returns: pd.Series) -> None:
    result = beta_alpha(random_returns, random_returns)
    assert result["beta"] == pytest.approx(1.0)
    assert result["alpha_annual"] == pytest.approx(0.0, abs=1e-12)
    assert result["r_squared"] == pytest.approx(1.0)


def test_beta_of_double_leverage_is_two(random_returns: pd.Series) -> None:
    result = beta_alpha(2.0 * random_returns, random_returns)
    assert result["beta"] == pytest.approx(2.0)


def test_alpha_is_detected_when_added(random_returns: pd.Series) -> None:
    """Adding a constant daily edge must show up as positive annual alpha."""
    result = beta_alpha(random_returns + 0.0002, random_returns)
    assert result["beta"] == pytest.approx(1.0)
    assert result["alpha_annual"] == pytest.approx(0.0002 * 252, rel=1e-6)


def test_beta_of_uncorrelated_series_is_near_zero() -> None:
    index = pd.bdate_range("2018-01-01", periods=2000, name="date")
    rng = np.random.default_rng(11)
    a = pd.Series(rng.normal(0, 0.01, len(index)), index=index)
    b = pd.Series(rng.normal(0, 0.01, len(index)), index=index)
    assert abs(beta_alpha(a, b)["beta"]) < 0.1


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------


def test_newey_west_tstat_is_large_for_a_strong_signal() -> None:
    index = pd.bdate_range("2018-01-01", periods=1008, name="date")
    rng = np.random.default_rng(3)
    strong = pd.Series(rng.normal(0.002, 0.005, len(index)), index=index)
    assert newey_west_tstat(strong)["tstat"] > 5


def test_newey_west_tstat_is_small_for_noise() -> None:
    index = pd.bdate_range("2018-01-01", periods=1008, name="date")
    rng = np.random.default_rng(4)
    noise = pd.Series(rng.normal(0.0, 0.01, len(index)), index=index)
    assert abs(newey_west_tstat(noise)["tstat"]) < 2.5


def test_newey_west_widens_se_under_positive_autocorrelation() -> None:
    """HAC correction must be doing real work, not returning the naive SE.

    With positively autocorrelated returns the effective sample size is smaller
    than the nominal one, so the standard error must be larger than the i.i.d.
    estimate. If these were equal, the correction would be decorative.
    """
    index = pd.bdate_range("2018-01-01", periods=2000, name="date")
    rng = np.random.default_rng(5)
    shocks = rng.normal(0, 0.01, len(index))
    autocorrelated = pd.Series(
        pd.Series(shocks).rolling(10, min_periods=1).mean().to_numpy(), index=index
    )
    hac = newey_west_tstat(autocorrelated, lags=21)
    naive_se = autocorrelated.std(ddof=1) / np.sqrt(len(autocorrelated))
    assert hac["se"] > naive_se


def test_bootstrap_ci_brackets_the_point_estimate(random_returns: pd.Series) -> None:
    result = bootstrap_sharpe_ci(random_returns, n_resamples=2000)
    assert result["ci_low"] < result["sharpe"] < result["ci_high"]
    assert result["n_resamples"] > 0


def test_bootstrap_is_reproducible(random_returns: pd.Series) -> None:
    """A fixed seed must give identical intervals across runs."""
    a = bootstrap_sharpe_ci(random_returns, n_resamples=1000, seed=42)
    b = bootstrap_sharpe_ci(random_returns, n_resamples=1000, seed=42)
    assert a == b


def test_bootstrap_ci_excludes_zero_for_a_strong_signal() -> None:
    index = pd.bdate_range("2018-01-01", periods=1008, name="date")
    rng = np.random.default_rng(6)
    strong = pd.Series(rng.normal(0.002, 0.005, len(index)), index=index)
    result = bootstrap_sharpe_ci(strong, n_resamples=2000)
    assert result["ci_low"] > 0
    assert result["p_positive"] > 0.99


def test_bootstrap_ci_includes_zero_for_noise() -> None:
    """Pure noise must not produce a confidently positive Sharpe interval."""
    index = pd.bdate_range("2018-01-01", periods=1008, name="date")
    rng = np.random.default_rng(8)
    noise = pd.Series(rng.normal(0.0, 0.01, len(index)), index=index)
    result = bootstrap_sharpe_ci(noise, n_resamples=2000)
    assert result["ci_low"] < 0 < result["ci_high"]


def test_bootstrap_declines_on_a_tiny_sample() -> None:
    index = pd.bdate_range("2020-01-01", periods=10, name="date")
    result = bootstrap_sharpe_ci(pd.Series(0.001, index=index))
    assert result["n_resamples"] == 0
    assert np.isnan(result["ci_low"])


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def test_summarise_returns_the_expected_keys(random_returns: pd.Series) -> None:
    benchmark = random_returns * 0.8
    turnover = pd.Series(
        0.4, index=pd.bdate_range("2018-01-01", periods=48, freq="ME")
    )
    summary = summarise(random_returns, rf=0.0001, benchmark=benchmark,
                        turnover=turnover)
    for key in (
        "total_return", "ann_return", "ann_volatility", "sharpe", "sortino",
        "max_drawdown", "calmar", "hit_rate", "profit_factor", "n_obs",
        "tstat_nw", "ann_turnover", "bm_beta", "bm_alpha_annual",
    ):
        assert key in summary, f"missing metric {key!r}"
    assert summary["n_obs"] == len(random_returns)
