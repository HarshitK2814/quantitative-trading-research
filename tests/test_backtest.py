"""Tests for the backtest engine.

Wherever possible these check against a **hand-computable answer** rather than
a regression snapshot. A snapshot test only proves the engine still does what it
did yesterday; it cannot tell you whether what it did yesterday was right.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.backtest import buy_and_hold, rebalance_schedule, run_backtest


@pytest.fixture
def flat_prices() -> pd.DataFrame:
    """Two assets whose prices never move. Every return must be exactly zero."""
    index = pd.bdate_range("2020-01-01", periods=60, name="date")
    return pd.DataFrame({"AAA": 100.0, "BBB": 50.0}, index=index)


@pytest.fixture
def trending_prices() -> pd.DataFrame:
    """AAA compounds at exactly +1%/day; BBB is flat."""
    index = pd.bdate_range("2020-01-01", periods=60, name="date")
    return pd.DataFrame(
        {"AAA": 100.0 * 1.01 ** np.arange(60), "BBB": 50.0}, index=index
    )


def _targets(index, weights: dict[str, float], dates=None) -> pd.DataFrame:
    """Build a target-weight frame that rebalances only on ``dates``."""
    frame = pd.DataFrame(np.nan, index=index, columns=list(weights))
    for asset, weight in weights.items():
        frame.loc[index[:1] if dates is None else dates, asset] = weight
    return frame


# ---------------------------------------------------------------------------
# Analytic correctness
# ---------------------------------------------------------------------------


def test_flat_prices_produce_zero_return(flat_prices: pd.DataFrame) -> None:
    """No price movement and no trading means no P&L."""
    targets = _targets(flat_prices.index, {"AAA": 0.5, "BBB": 0.5})
    result = run_backtest(flat_prices, targets, cost_bps=0.0)
    assert result.returns.abs().max() < 1e-12
    assert result.equity.iloc[-1] == pytest.approx(1.0)


def test_full_allocation_matches_the_asset_exactly(
    trending_prices: pd.DataFrame,
) -> None:
    """100% in a single asset must reproduce that asset's return stream."""
    targets = _targets(trending_prices.index, {"AAA": 1.0, "BBB": 0.0})
    result = run_backtest(trending_prices, targets, cost_bps=0.0)

    expected = trending_prices["AAA"].pct_change().fillna(0.0)
    pd.testing.assert_series_equal(
        result.returns, expected, check_names=False, atol=1e-12
    )
    # +1%/day for 59 compounding days.
    assert result.equity.iloc[-1] == pytest.approx(1.01**59, rel=1e-9)


def test_uninvested_portfolio_earns_only_the_risk_free_rate(
    trending_prices: pd.DataFrame,
) -> None:
    """Zero weights means 100% cash, which must earn exactly rf."""
    targets = _targets(trending_prices.index, {"AAA": 0.0, "BBB": 0.0})
    rf = pd.Series(0.0001, index=trending_prices.index)
    result = run_backtest(trending_prices, targets, cost_bps=0.0, rf_daily=rf)

    assert result.cash_weight.round(12).eq(1.0).all()
    np.testing.assert_allclose(result.returns.to_numpy(), 0.0001, atol=1e-12)


def test_cost_is_charged_exactly_once_on_the_initial_trade(
    flat_prices: pd.DataFrame,
) -> None:
    """Buying 50/50 from cash is 1.0 turnover, so 10bps costs exactly 10bps."""
    targets = _targets(flat_prices.index, {"AAA": 0.5, "BBB": 0.5})
    result = run_backtest(flat_prices, targets, cost_bps=10.0)

    assert len(result.turnover) == 1
    assert result.turnover.iloc[0] == pytest.approx(1.0)
    assert result.costs.sum() == pytest.approx(0.0010)
    assert result.returns.iloc[0] == pytest.approx(-0.0010)


def test_turnover_is_zero_when_targets_already_match(
    flat_prices: pd.DataFrame,
) -> None:
    """Re-requesting the weights you already hold must not incur cost."""
    every_day = flat_prices.index
    targets = _targets(flat_prices.index, {"AAA": 0.5, "BBB": 0.5}, dates=every_day)
    result = run_backtest(flat_prices, targets, cost_bps=10.0)

    assert result.turnover.iloc[0] == pytest.approx(1.0)  # initial purchase
    assert result.turnover.iloc[1:].abs().max() < 1e-12  # nothing thereafter
    assert result.costs.sum() == pytest.approx(0.0010)


# ---------------------------------------------------------------------------
# Weight drift -- the property naive engines get wrong
# ---------------------------------------------------------------------------


def test_weights_drift_between_rebalances(trending_prices: pd.DataFrame) -> None:
    """Held weights must move with prices even though no trade occurred.

    Terminal weights are asserted against the closed form rather than a guessed
    bound: with a single purchase at t0, each asset's share is simply its
    relative cumulative growth.
    """
    targets = _targets(trending_prices.index, {"AAA": 0.5, "BBB": 0.5})
    result = run_backtest(trending_prices, targets, cost_bps=0.0)

    assert result.weights.iloc[0]["AAA"] == pytest.approx(0.5)
    assert len(result.rebalance_dates) == 1

    # Weights are those held at the START of each day, so the last row reflects
    # growth through the previous close.
    growth_aaa = trending_prices["AAA"].iloc[-2] / trending_prices["AAA"].iloc[0]
    growth_bbb = trending_prices["BBB"].iloc[-2] / trending_prices["BBB"].iloc[0]
    expected_aaa = 0.5 * growth_aaa / (0.5 * growth_aaa + 0.5 * growth_bbb)

    last = result.weights.iloc[-1]
    assert last["AAA"] == pytest.approx(expected_aaa)
    assert last["AAA"] > 0.5  # the winner's share must have grown
    assert last["BBB"] < 0.5
    assert last.sum() == pytest.approx(1.0)


def test_drift_is_arithmetically_correct(trending_prices: pd.DataFrame) -> None:
    """Check the drift formula against an explicit hand calculation.

    ``weights`` records holdings at the **start** of each day, so row 1 still
    shows the freshly-purchased 50/50: the day-1 return has not been applied
    yet. Drift from that return first appears in row 2, where AAA gained 1%,
    BBB gained 0%, and the portfolio therefore grew 0.5%.
    """
    targets = _targets(trending_prices.index, {"AAA": 0.5, "BBB": 0.5})
    result = run_backtest(trending_prices, targets, cost_bps=0.0)

    # Start of day 1: purchased, but no return applied yet.
    assert result.weights.iloc[1]["AAA"] == pytest.approx(0.5)

    # Start of day 2: one day of drift.
    day_two = result.weights.iloc[2]
    assert day_two["AAA"] == pytest.approx(0.5 * 1.01 / 1.005)
    assert day_two["BBB"] == pytest.approx(0.5 * 1.00 / 1.005)
    assert day_two.sum() == pytest.approx(1.0)


def test_rebalancing_costs_more_than_buy_and_hold(
    trending_prices: pd.DataFrame,
) -> None:
    """Monthly rebalancing must incur strictly more cost than trading once.

    This is the concrete consequence of modelling drift. An engine that pinned
    weights to their targets would show no such difference, because it would be
    silently rebalancing for free every day.
    """
    held = buy_and_hold(trending_prices, {"AAA": 0.5, "BBB": 0.5}, cost_bps=10.0)
    rebalanced = buy_and_hold(
        trending_prices, {"AAA": 0.5, "BBB": 0.5}, rebalance="ME", cost_bps=10.0
    )
    assert rebalanced.costs.sum() > held.costs.sum()
    assert len(rebalanced.rebalance_dates) > len(held.rebalance_dates)


# ---------------------------------------------------------------------------
# Cost monotonicity
# ---------------------------------------------------------------------------


def test_higher_costs_monotonically_reduce_returns(
    trending_prices: pd.DataFrame,
) -> None:
    """Final equity must fall monotonically as the cost assumption rises."""
    finals = []
    for bps in (0.0, 5.0, 10.0, 20.0):
        result = buy_and_hold(
            trending_prices, {"AAA": 0.5, "BBB": 0.5}, rebalance="ME", cost_bps=bps
        )
        finals.append(result.equity.iloc[-1])
    assert finals == sorted(finals, reverse=True)
    assert finals[0] > finals[-1]


def test_zero_cost_gross_equals_net(trending_prices: pd.DataFrame) -> None:
    """With no costs, the gross and net series must be identical."""
    targets = _targets(trending_prices.index, {"AAA": 0.5, "BBB": 0.5})
    result = run_backtest(trending_prices, targets, cost_bps=0.0)
    pd.testing.assert_series_equal(
        result.returns, result.gross_returns, check_names=False
    )


def test_net_is_gross_minus_cost(trending_prices: pd.DataFrame) -> None:
    targets = _targets(trending_prices.index, {"AAA": 0.5, "BBB": 0.5})
    result = run_backtest(trending_prices, targets, cost_bps=20.0)
    np.testing.assert_allclose(
        result.returns.to_numpy(),
        (result.gross_returns - result.costs).to_numpy(),
        atol=1e-15,
    )


# ---------------------------------------------------------------------------
# Input validation -- fail loudly rather than produce a plausible wrong answer
# ---------------------------------------------------------------------------


def test_negative_weights_are_rejected(flat_prices: pd.DataFrame) -> None:
    """Shorting is not simulated, so a short request must raise."""
    targets = _targets(flat_prices.index, {"AAA": 1.2, "BBB": -0.2})
    with pytest.raises(ValueError, match="long-only"):
        run_backtest(flat_prices, targets)


def test_leverage_is_rejected(flat_prices: pd.DataFrame) -> None:
    """Gross exposure above 1.0 would need margin, which is not modelled."""
    targets = _targets(flat_prices.index, {"AAA": 0.8, "BBB": 0.8})
    with pytest.raises(ValueError, match="exceeds 1.0"):
        run_backtest(flat_prices, targets)


def test_disjoint_assets_are_rejected(flat_prices: pd.DataFrame) -> None:
    targets = pd.DataFrame(
        {"ZZZ": 1.0}, index=flat_prices.index
    )
    with pytest.raises(ValueError, match="No overlapping assets"):
        run_backtest(flat_prices, targets)


def test_open_execution_requires_open_prices(flat_prices: pd.DataFrame) -> None:
    targets = _targets(flat_prices.index, {"AAA": 0.5, "BBB": 0.5})
    with pytest.raises(ValueError, match="requires open_prices"):
        run_backtest(flat_prices, targets, execution="open")


# ---------------------------------------------------------------------------
# Rebalance scheduling
# ---------------------------------------------------------------------------


def test_schedule_only_returns_actual_trading_days() -> None:
    """Month-ends falling on a weekend must resolve to a real session."""
    index = pd.bdate_range("2020-01-01", "2020-12-31", name="date")
    schedule = rebalance_schedule(index, "ME")
    assert len(schedule) == 12
    assert schedule.isin(index).all()
    assert not schedule.weekday.isin([5, 6]).any()


def test_daily_schedule_is_every_day() -> None:
    index = pd.bdate_range("2020-01-01", periods=40, name="date")
    assert rebalance_schedule(index, "D").equals(index)


def test_weekly_schedule_is_denser_than_monthly() -> None:
    index = pd.bdate_range("2020-01-01", "2020-12-31", name="date")
    assert len(rebalance_schedule(index, "W-FRI")) > len(
        rebalance_schedule(index, "ME")
    )


# ---------------------------------------------------------------------------
# Look-ahead: the engine must not peek either
# ---------------------------------------------------------------------------


def test_returns_before_a_cutoff_are_unaffected_by_later_prices() -> None:
    """Shift-invariance applied to the engine, not just to the features.

    Features being causal is necessary but not sufficient: the engine itself
    could still read ahead, for instance by marking a trade at a future price.
    """
    index = pd.bdate_range("2020-01-01", periods=300, name="date")
    rng = np.random.default_rng(7)
    prices = pd.DataFrame(
        {
            t: 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(index))))
            for t in ("AAA", "BBB", "CCC")
        },
        index=index,
    )
    schedule = rebalance_schedule(index, "ME")
    targets = _targets(index, {"AAA": 0.3, "BBB": 0.3, "CCC": 0.3}, dates=schedule)

    cutoff = index[200]
    perturbed = prices.copy()
    future = perturbed.index > cutoff
    perturbed.loc[future, :] = rng.uniform(10, 500, size=(int(future.sum()), 3))

    baseline = run_backtest(prices, targets, cost_bps=10.0).returns.loc[:cutoff]
    recomputed = run_backtest(perturbed, targets, cost_bps=10.0).returns.loc[:cutoff]
    pd.testing.assert_series_equal(baseline, recomputed, check_exact=True)


# ---------------------------------------------------------------------------
# Bookkeeping
# ---------------------------------------------------------------------------


def test_weights_and_cash_always_sum_to_one(trending_prices: pd.DataFrame) -> None:
    """Accounting identity: invested plus cash is the whole portfolio."""
    targets = _targets(trending_prices.index, {"AAA": 0.4, "BBB": 0.3})
    result = run_backtest(trending_prices, targets, cost_bps=0.0)
    total = result.weights.sum(axis=1) + result.cash_weight
    np.testing.assert_allclose(total.to_numpy(), 1.0, atol=1e-12)


def test_config_records_the_run_parameters(flat_prices: pd.DataFrame) -> None:
    """A result must be traceable to the inputs that produced it."""
    targets = _targets(flat_prices.index, {"AAA": 0.5, "BBB": 0.5})
    result = run_backtest(flat_prices, targets, cost_bps=7.5)
    assert result.config["cost_bps"] == 7.5
    assert result.config["execution"] == "close"
    assert result.config["n_assets"] == 2
    assert result.config["trading_days_per_year"] == 252
