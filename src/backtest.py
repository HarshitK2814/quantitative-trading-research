"""Vectorised daily backtest engine.

Scope and rationale
-------------------
This engine simulates a **long-only, daily-frequency, portfolio-weight**
strategy: at each rebalance date a target weight vector is supplied, and the
engine trades the difference from what is currently held. See ``PROJECT_PLAN.md``
section 3.1 for why a purpose-built engine was chosen over Backtrader, including
the argument against that choice.

It is deliberately small enough to read in full. Everything it does is listed
here, and everything it does *not* do is listed under Limitations.

The one thing this engine gets right that naive backtests get wrong
-------------------------------------------------------------------
**Positions drift between rebalances.** If you hold 50/50 in two assets and one
doubles, you now hold 67/33 -- you did not trade, the market moved you. A
backtest that assumes weights stay at their targets between rebalances is
wrong in two directions at once:

* It **overstates turnover**, because it charges the cost of restoring 50/50
  every single day rather than only at rebalance dates.
* It **misstates returns**, because it implicitly rebalances daily for free,
  which quietly harvests a rebalancing premium that was never available.

This engine tracks drifted weights explicitly and computes turnover as the
distance between the *drifted* holdings and the new targets. That is what a
real portfolio actually trades.

Limitations (stated, not hidden)
--------------------------------
* **Fills are assumed at the reference price** (next open or next close). No
  spread crossing, no market impact, no partial fills, no queue position. The
  cost model in ``research/transaction_cost_model.md`` is a proxy for all of
  these, and it is an assumption rather than a measurement.
* **No intraday path.** Stops and intraday risk limits cannot be simulated.
* **No borrow, no leverage, no shorting.** Long-only by construction.
* **Dividends are inside the price series** (adjusted closes), so they are
  reinvested implicitly and instantaneously, with no withholding tax.
* **Cash earns the risk-free rate** when supplied, and zero otherwise.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from src.config import COSTS, TRADING_DAYS_PER_YEAR

logger = logging.getLogger(__name__)

ExecutionPrice = Literal["close", "open"]

_EPS = 1e-12
_WEIGHT_TOLERANCE = 1e-9


@dataclass
class BacktestResult:
    """Output of a backtest run.

    Attributes:
        returns: Net daily portfolio returns, after costs.
        gross_returns: Daily portfolio returns before costs.
        weights: Weights actually held at the start of each day, after drift.
        turnover: One-way turnover on each rebalance date, as a fraction of
            portfolio value.
        costs: Cost charged on each date, as a fraction of portfolio value.
        cash_weight: Fraction held in cash each day.
        rebalance_dates: Dates on which trading occurred.
        config: Run parameters, recorded so a result can be traced to its inputs.

    """

    returns: pd.Series
    gross_returns: pd.Series
    weights: pd.DataFrame
    turnover: pd.Series
    costs: pd.Series
    cash_weight: pd.Series
    rebalance_dates: pd.DatetimeIndex
    config: dict = field(default_factory=dict)

    @property
    def equity(self) -> pd.Series:
        """Compounded net equity curve, starting at 1.0."""
        return (1.0 + self.returns.fillna(0.0)).cumprod()

    def summary(self) -> str:
        """Short text summary for logs and notebooks."""
        return (
            f"Backtest {self.returns.index.min().date()} .. "
            f"{self.returns.index.max().date()} | "
            f"{len(self.returns)} days | {len(self.rebalance_dates)} rebalances | "
            f"final equity {self.equity.iloc[-1]:.3f} | "
            f"total cost {self.costs.sum():.4f}"
        )


def rebalance_schedule(
    index: pd.DatetimeIndex, frequency: str = "ME"
) -> pd.DatetimeIndex:
    """Return the trading dates on which rebalancing occurs.

    Args:
        index: The full trading-day index.
        frequency: A pandas offset alias -- ``"ME"`` month-end, ``"W-FRI"``
            weekly, ``"QE"`` quarter-end, or ``"D"`` for every day.

    Returns:
        The subset of ``index`` on which to rebalance. Because the last *actual*
        trading day of each period is selected, calendar month-ends that fall on
        weekends or holidays resolve to the preceding session -- never to a date
        the market was closed.

    """
    if frequency.upper() == "D":
        return index

    grouped = pd.Series(index, index=index).groupby(
        pd.Grouper(freq=frequency)
    ).last()
    return pd.DatetimeIndex(grouped.dropna().to_numpy())


def run_backtest(
    prices: pd.DataFrame,
    target_weights: pd.DataFrame,
    cost_bps: float | None = None,
    rf_daily: pd.Series | None = None,
    execution: ExecutionPrice = "close",
    open_prices: pd.DataFrame | None = None,
    initial_cash_rate: float = 0.0,
) -> BacktestResult:
    """Simulate a long-only weight-based strategy.

    Args:
        prices: Adjusted close panel, indexed by date, one column per asset.
        target_weights: Desired weights, indexed by date. **Must already be
            lagged** by ``src.features.make_tradable`` -- this function does not
            shift, so that look-ahead protection stays in exactly one place.
            Rows that are entirely NaN are treated as "no rebalance today".
            Weights need not sum to 1; the remainder is held as cash.
        cost_bps: One-way transaction cost in basis points per unit turnover.
            Defaults to the project headline (10 bps).
        rf_daily: Daily risk-free rate earned on the cash portion.
        execution: Whether to mark positions at the close or the open.
        open_prices: Required when ``execution="open"``.
        initial_cash_rate: Unused placeholder retained for signature stability.

    Returns:
        A :class:`BacktestResult`.

    Raises:
        ValueError: If inputs are misaligned, weights are negative, gross
            exposure exceeds 1, or ``execution="open"`` without ``open_prices``.

    """
    del initial_cash_rate  # retained for signature stability

    cost_rate = COSTS.cost_fraction(cost_bps)

    if execution == "open":
        if open_prices is None:
            raise ValueError("execution='open' requires open_prices.")
        marking_prices = open_prices
    else:
        marking_prices = prices

    # Align everything to the common trading calendar and asset set.
    assets = [c for c in prices.columns if c in target_weights.columns]
    if not assets:
        raise ValueError("No overlapping assets between prices and target_weights.")

    index = prices.index.intersection(target_weights.index)
    if len(index) < 2:
        raise ValueError("Fewer than two overlapping dates to simulate.")

    price_panel = marking_prices.loc[index, assets]
    weight_panel = target_weights.loc[index, assets]

    asset_returns = price_panel.pct_change(fill_method=None).fillna(0.0)

    # Validate the weights before simulating, so a bad strategy fails loudly
    # rather than producing a plausible-looking but meaningless equity curve.
    if (weight_panel.fillna(0.0) < -_WEIGHT_TOLERANCE).any().any():
        raise ValueError(
            "Negative target weights found. This engine is long-only; shorting "
            "is not simulated and would silently produce wrong results."
        )
    gross = weight_panel.fillna(0.0).sum(axis=1)
    if (gross > 1.0 + _WEIGHT_TOLERANCE).any():
        worst = gross.max()
        raise ValueError(
            f"Gross exposure {worst:.4f} exceeds 1.0. This engine does not "
            f"simulate leverage or margin interest."
        )

    rf = (
        rf_daily.reindex(index).ffill().bfill().fillna(0.0)
        if rf_daily is not None
        else pd.Series(0.0, index=index)
    )

    # A rebalance happens on any date with a non-empty target row.
    has_target = weight_panel.notna().any(axis=1)

    n_dates, n_assets = len(index), len(assets)
    held = np.zeros(n_assets)  # weights at the START of each day

    held_history = np.zeros((n_dates, n_assets))
    gross_history = np.zeros(n_dates)
    net_history = np.zeros(n_dates)
    turnover_history = np.full(n_dates, np.nan)
    cost_history = np.zeros(n_dates)
    cash_history = np.zeros(n_dates)

    returns_matrix = asset_returns.to_numpy()
    weights_matrix = weight_panel.to_numpy()
    rf_values = rf.to_numpy()
    rebalance_flags = has_target.to_numpy()
    rebalance_dates: list[pd.Timestamp] = []

    for day in range(n_dates):
        # 1. Rebalance BEFORE the day's return, using yesterday's information.
        #    target_weights is already lagged, so the row at `day` was formed
        #    from data through day-1 at the latest.
        if rebalance_flags[day]:
            target = np.nan_to_num(weights_matrix[day], nan=0.0)
            turnover = float(np.abs(target - held).sum())
            cost = turnover * cost_rate

            held = target
            turnover_history[day] = turnover
            cost_history[day] = cost
            rebalance_dates.append(index[day])

        held_history[day] = held
        cash_weight = 1.0 - held.sum()
        cash_history[day] = cash_weight

        # 2. Apply the day's returns to the positions held at its start.
        asset_pnl = float(np.dot(held, returns_matrix[day]))
        cash_pnl = cash_weight * rf_values[day]
        gross_return = asset_pnl + cash_pnl

        gross_history[day] = gross_return
        net_history[day] = gross_return - cost_history[day]

        # 3. Drift: positions grow with their own returns, so weights change
        #    without any trade. This is the step naive backtests omit.
        portfolio_growth = 1.0 + gross_return
        if abs(portfolio_growth) > _EPS:
            held = held * (1.0 + returns_matrix[day]) / portfolio_growth

    return BacktestResult(
        returns=pd.Series(net_history, index=index, name="net_return"),
        gross_returns=pd.Series(gross_history, index=index, name="gross_return"),
        weights=pd.DataFrame(held_history, index=index, columns=assets),
        turnover=pd.Series(turnover_history, index=index, name="turnover").dropna(),
        costs=pd.Series(cost_history, index=index, name="cost"),
        cash_weight=pd.Series(cash_history, index=index, name="cash_weight"),
        rebalance_dates=pd.DatetimeIndex(rebalance_dates),
        config={
            "cost_bps": COSTS.headline_bps if cost_bps is None else cost_bps,
            "execution": execution,
            "n_assets": n_assets,
            "n_dates": n_dates,
            "risk_free_applied": rf_daily is not None,
            "trading_days_per_year": TRADING_DAYS_PER_YEAR,
        },
    )


def buy_and_hold(
    prices: pd.DataFrame,
    weights: dict[str, float] | None = None,
    rebalance: str | None = None,
    cost_bps: float | None = None,
    rf_daily: pd.Series | None = None,
) -> BacktestResult:
    """Construct a benchmark portfolio.

    Args:
        prices: Adjusted close panel.
        weights: Asset weights. Defaults to equal weight across all columns.
        rebalance: Offset alias to rebalance on (e.g. ``"ME"``). ``None`` means
            buy once at the start and never trade again -- true buy-and-hold,
            which drifts freely.
        cost_bps: Transaction cost in basis points.
        rf_daily: Daily risk-free rate for the cash portion.

    Returns:
        A :class:`BacktestResult` for the benchmark.

    """
    if weights is None:
        weights = {c: 1.0 / prices.shape[1] for c in prices.columns}

    targets = pd.DataFrame(np.nan, index=prices.index, columns=prices.columns)
    schedule = (
        prices.index[:1]
        if rebalance is None
        else rebalance_schedule(prices.index, rebalance)
    )
    for asset, weight in weights.items():
        if asset in targets.columns:
            targets.loc[schedule, asset] = weight

    return run_backtest(
        prices, targets, cost_bps=cost_bps, rf_daily=rf_daily
    )
