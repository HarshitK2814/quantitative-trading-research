"""Performance and risk metrics, with every convention stated explicitly.

Why the conventions are documented rather than assumed
------------------------------------------------------
A Sharpe ratio quoted without its annualisation factor, return frequency, and
risk-free convention is not a falsifiable number -- two people can compute
"the Sharpe" of the same return stream and differ by 30% without either making
an arithmetic error. Every function here therefore states its convention in the
docstring, and the conventions are:

* **Returns** are simple (arithmetic) daily returns, not log returns. Simple
  returns are what a portfolio actually earns and what aggregates correctly
  across assets within a period.
* **Annualisation** uses 252 trading days. Volatility scales by sqrt(252),
  return by geometric compounding rather than multiplication by 252.
* **Excess returns** subtract a daily risk-free rate derived from FRED DTB3
  (see :func:`src.data.load_risk_free_rate`). Passing ``rf=None`` computes a
  raw Sharpe, which is reported as such and never labelled simply "Sharpe".
* **Drawdown** is computed on the compounded equity curve, peak-to-trough.

Statistical caveat that applies throughout
------------------------------------------
Daily financial returns are not i.i.d. -- they are heteroskedastic, fat-tailed,
and mildly autocorrelated. The classical standard error of a Sharpe ratio
therefore understates uncertainty. :func:`newey_west_tstat` and
:func:`bootstrap_sharpe_ci` exist because of this, and any Sharpe reported
without an interval alongside it should be treated as a point estimate of
unknown precision.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import RANDOM_SEED, TRADING_DAYS_PER_YEAR

_EPS = 1e-12


# ---------------------------------------------------------------------------
# Return aggregation
# ---------------------------------------------------------------------------


def to_excess(returns: pd.Series, rf: pd.Series | float | None = None) -> pd.Series:
    """Subtract the risk-free rate from a return series.

    Args:
        returns: Simple daily returns.
        rf: Daily risk-free rate. A Series is aligned on the index; a float is
            treated as a constant daily rate; ``None`` returns ``returns``
            unchanged (a *raw*, not excess, series).

    Returns:
        Excess daily returns.

    """
    if rf is None:
        return returns
    if isinstance(rf, pd.Series):
        return returns - rf.reindex(returns.index).ffill().bfill()
    return returns - float(rf)


def equity_curve(returns: pd.Series, initial: float = 1.0) -> pd.Series:
    """Compound a return series into an equity curve.

    Args:
        returns: Simple daily returns. NaNs are treated as zero-return days,
            since a day with no observation is a day the portfolio did not move.
        initial: Starting value.

    Returns:
        Compounded equity, same index as ``returns``.

    """
    return initial * (1.0 + returns.fillna(0.0)).cumprod()


def total_return(returns: pd.Series) -> float:
    """Cumulative compounded return over the whole sample, as a decimal."""
    return float((1.0 + returns.fillna(0.0)).prod() - 1.0)


def annualised_return(returns: pd.Series) -> float:
    """Geometric annualised return (CAGR).

    Uses geometric compounding, ``(1+total)**(252/n) - 1``, not the arithmetic
    mean times 252. The arithmetic version overstates compounded growth whenever
    returns are volatile, and the gap widens with volatility -- which is exactly
    when a strategy most wants to look good.
    """
    clean = returns.dropna()
    if len(clean) == 0:
        return float("nan")
    growth = float((1.0 + clean).prod())
    if growth <= 0:
        return -1.0
    return growth ** (TRADING_DAYS_PER_YEAR / len(clean)) - 1.0


def annualised_volatility(returns: pd.Series) -> float:
    """Annualised standard deviation of daily returns (sample, ddof=1)."""
    clean = returns.dropna()
    if len(clean) < 2:
        return float("nan")
    return float(clean.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))


# ---------------------------------------------------------------------------
# Risk-adjusted metrics
# ---------------------------------------------------------------------------


def sharpe_ratio(
    returns: pd.Series, rf: pd.Series | float | None = None
) -> float:
    """Annualised Sharpe ratio of excess returns.

    Computed as ``mean(excess) / std(excess) * sqrt(252)``, using the arithmetic
    mean of daily excess returns and the sample standard deviation (ddof=1).

    Args:
        returns: Simple daily returns.
        rf: Daily risk-free rate, or ``None`` for a raw Sharpe.

    Returns:
        Annualised Sharpe ratio, or NaN if volatility is zero or the sample is
        too short.

    """
    excess = to_excess(returns, rf).dropna()
    if len(excess) < 2:
        return float("nan")
    std = excess.std(ddof=1)
    if std < _EPS:
        return float("nan")
    return float(excess.mean() / std * np.sqrt(TRADING_DAYS_PER_YEAR))


def sortino_ratio(
    returns: pd.Series, rf: pd.Series | float | None = None
) -> float:
    """Annualised Sortino ratio, penalising only downside deviation.

    Downside deviation is computed over **all** observations with upside
    clipped to zero, not over the subset of negative days. Averaging only the
    negative days would divide by a smaller count and inflate the ratio -- a
    common and quietly flattering error.
    """
    excess = to_excess(returns, rf).dropna()
    if len(excess) < 2:
        return float("nan")
    downside = excess.clip(upper=0.0)
    downside_deviation = np.sqrt((downside**2).mean())
    if downside_deviation < _EPS:
        return float("nan")
    return float(
        excess.mean() / downside_deviation * np.sqrt(TRADING_DAYS_PER_YEAR)
    )


def drawdown_series(returns: pd.Series) -> pd.Series:
    """Drawdown from the running peak of the compounded equity curve.

    Returns:
        Series of non-positive values, where -0.20 means 20% below the peak.

    """
    curve = equity_curve(returns)
    return curve / curve.cummax() - 1.0


def max_drawdown(returns: pd.Series) -> float:
    """Worst peak-to-trough decline, as a negative decimal."""
    drawdowns = drawdown_series(returns)
    return float(drawdowns.min()) if len(drawdowns) else float("nan")


def calmar_ratio(returns: pd.Series) -> float:
    """Annualised return divided by the absolute maximum drawdown.

    Note:
        Calmar is highly sample-dependent: the denominator is a single extreme
        observation, so the ratio is dominated by whether the sample happens to
        contain a crisis. Read it alongside Sharpe, never instead of it.

    """
    worst = abs(max_drawdown(returns))
    if worst < _EPS:
        return float("nan")
    return annualised_return(returns) / worst


def drawdown_details(returns: pd.Series) -> dict[str, object]:
    """Locate and characterise the worst drawdown.

    Returns:
        Mapping with the peak, trough, and recovery dates, the depth, and the
        durations in trading days. ``recovery_date`` is ``None`` and
        ``recovery_days`` is NaN if the series never regained its prior peak.

    """
    curve = equity_curve(returns)
    drawdowns = curve / curve.cummax() - 1.0
    if drawdowns.empty:
        return {}

    trough_date = drawdowns.idxmin()
    peak_date = curve.loc[:trough_date].idxmax()

    after = curve.loc[trough_date:]
    peak_value = curve.loc[peak_date]
    recovered = after[after >= peak_value]
    recovery_date = recovered.index[0] if len(recovered) else None

    positions = curve.index
    to_trough = int(positions.get_loc(trough_date) - positions.get_loc(peak_date))
    recovery_days = (
        int(positions.get_loc(recovery_date) - positions.get_loc(trough_date))
        if recovery_date is not None
        else float("nan")
    )

    return {
        "peak_date": peak_date,
        "trough_date": trough_date,
        "recovery_date": recovery_date,
        "max_drawdown": float(drawdowns.min()),
        "days_peak_to_trough": to_trough,
        "days_trough_to_recovery": recovery_days,
    }


# ---------------------------------------------------------------------------
# Trade-level statistics
# ---------------------------------------------------------------------------


def hit_rate(returns: pd.Series) -> float:
    """Fraction of observations with a strictly positive return.

    Note:
        Hit rate is nearly uninformative on its own. A strategy winning 70% of
        days can still lose money if the losing days are large. Always read it
        with :func:`profit_factor`.

    """
    clean = returns.dropna()
    if len(clean) == 0:
        return float("nan")
    return float((clean > 0).mean())


def profit_factor(returns: pd.Series) -> float:
    """Gross gains divided by gross losses."""
    clean = returns.dropna()
    gains = clean[clean > 0].sum()
    losses = -clean[clean < 0].sum()
    if losses < _EPS:
        return float("inf") if gains > 0 else float("nan")
    return float(gains / losses)


def annualised_turnover(
    turnover: pd.Series, n_trading_days: int | None = None
) -> float:
    """Annualise a per-rebalance turnover series.

    Turnover is recorded **only on rebalance dates**, so it is a sparse series:
    twelve monthly rebalances produce twelve observations spanning a year, not
    twelve days. Annualising by the observation *count* would therefore scale a
    monthly strategy as though it traded on twelve consecutive days and inflate
    the figure by roughly 21x. The elapsed period is what matters, not how many
    times it was sampled.

    Args:
        turnover: One-way turnover per rebalance, as a fraction of portfolio
            value (the sum of absolute weight changes).
        n_trading_days: Total trading days in the backtest. Preferred, since it
            is exact. When omitted, the elapsed span of the turnover index is
            used instead, which is approximate for short or irregular samples.

    Returns:
        Total turnover per year, so 2.0 means the portfolio is fully replaced
        twice annually.

    """
    clean = turnover.dropna()
    if len(clean) == 0:
        return float("nan")

    if n_trading_days is not None and n_trading_days > 0:
        years = n_trading_days / TRADING_DAYS_PER_YEAR
    else:
        if len(clean) < 2:
            return float("nan")
        elapsed_days = (clean.index[-1] - clean.index[0]).days
        if elapsed_days <= 0:
            return float("nan")
        # Scale by the mean gap so a full final period is counted, not just the
        # span between the first and last observations.
        mean_gap = elapsed_days / (len(clean) - 1)
        years = (elapsed_days + mean_gap) / 365.25

    if years <= 0:
        return float("nan")
    return float(clean.sum() / years)


# ---------------------------------------------------------------------------
# Benchmark-relative metrics
# ---------------------------------------------------------------------------


def beta_alpha(
    returns: pd.Series,
    benchmark: pd.Series,
    rf: pd.Series | float | None = None,
) -> dict[str, float]:
    """Regress excess strategy returns on excess benchmark returns.

    This is the check that separates a genuine result from a leveraged market
    bet. On a universe that is 12/16 equity ETFs, a strategy can post a fine
    Sharpe purely by holding more equity beta than the benchmark.

    Args:
        returns: Strategy daily returns.
        benchmark: Benchmark daily returns.
        rf: Daily risk-free rate.

    Returns:
        Mapping with ``beta``, ``alpha_annual`` (the intercept, annualised by
        252), ``r_squared``, ``correlation``, and ``n_obs``.

    """
    strategy_excess = to_excess(returns, rf)
    benchmark_excess = to_excess(benchmark, rf)
    both = pd.concat(
        [strategy_excess.rename("y"), benchmark_excess.rename("x")], axis=1
    ).dropna()

    if len(both) < 3:
        return {
            "beta": float("nan"), "alpha_annual": float("nan"),
            "r_squared": float("nan"), "correlation": float("nan"), "n_obs": 0,
        }

    x, y = both["x"].to_numpy(), both["y"].to_numpy()
    variance = x.var(ddof=1)
    if variance < _EPS:
        return {
            "beta": float("nan"), "alpha_annual": float("nan"),
            "r_squared": float("nan"), "correlation": float("nan"),
            "n_obs": len(both),
        }

    beta = float(np.cov(y, x, ddof=1)[0, 1] / variance)
    alpha_daily = float(y.mean() - beta * x.mean())
    correlation = float(np.corrcoef(y, x)[0, 1])

    return {
        "beta": beta,
        # Annualised by multiplication: alpha is a per-period mean, not a
        # compounded growth rate, so geometric scaling would be wrong here.
        "alpha_annual": alpha_daily * TRADING_DAYS_PER_YEAR,
        "r_squared": correlation**2,
        "correlation": correlation,
        "n_obs": len(both),
    }


# ---------------------------------------------------------------------------
# Statistical inference
# ---------------------------------------------------------------------------


def newey_west_tstat(returns: pd.Series, lags: int = 21) -> dict[str, float]:
    """t-statistic on the mean daily return, robust to autocorrelation.

    Uses a Newey-West HAC estimator with Bartlett weights. The classical
    t-statistic assumes i.i.d. observations; daily returns are heteroskedastic
    and mildly autocorrelated, so the classical version overstates significance.

    Args:
        returns: Daily returns (pass excess returns to test excess of cash).
        lags: Truncation lag. 21 ~ one trading month.

    Returns:
        Mapping with ``mean_daily``, ``se``, ``tstat``, and ``n_obs``.

    """
    clean = returns.dropna()
    n = len(clean)
    if n < lags + 2:
        return {
            "mean_daily": float("nan"), "se": float("nan"),
            "tstat": float("nan"), "n_obs": n,
        }

    values = clean.to_numpy()
    demeaned = values - values.mean()

    variance = float((demeaned**2).mean())
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1.0)  # Bartlett kernel
        autocovariance = float((demeaned[lag:] * demeaned[:-lag]).mean())
        variance += 2.0 * weight * autocovariance

    # A HAC estimate can go negative in small samples; fall back rather than
    # emit a NaN that would silently disappear from a results table.
    if variance <= 0:
        variance = float((demeaned**2).mean())

    standard_error = float(np.sqrt(variance / n))
    if standard_error < _EPS:
        return {
            "mean_daily": float(values.mean()), "se": 0.0,
            "tstat": float("nan"), "n_obs": n,
        }

    return {
        "mean_daily": float(values.mean()),
        "se": standard_error,
        "tstat": float(values.mean() / standard_error),
        "n_obs": n,
    }


def bootstrap_sharpe_ci(
    returns: pd.Series,
    rf: pd.Series | float | None = None,
    n_resamples: int = 10_000,
    expected_block: int = 21,
    confidence: float = 0.95,
    seed: int = RANDOM_SEED,
) -> dict[str, float]:
    """Stationary-bootstrap confidence interval for the Sharpe ratio.

    Uses the Politis-Romano stationary bootstrap: blocks of geometrically
    distributed length are sampled with replacement and wrapped circularly.
    Resampling *blocks* rather than individual days preserves the local
    dependence structure -- volatility clustering and autocorrelation -- that an
    i.i.d. bootstrap would destroy, and destroying it produces intervals that
    are far too narrow.

    Args:
        returns: Daily returns.
        rf: Daily risk-free rate.
        n_resamples: Number of bootstrap replications.
        expected_block: Mean block length in days. 21 ~ one trading month.
        confidence: Interval coverage, e.g. 0.95.
        seed: RNG seed, fixed for reproducibility.

    Returns:
        Mapping with ``sharpe`` (point estimate), ``ci_low``, ``ci_high``,
        ``p_positive`` (fraction of resamples with Sharpe > 0), and
        ``n_resamples``.

    """
    excess = to_excess(returns, rf).dropna()
    n = len(excess)
    if n < 30:
        return {
            "sharpe": sharpe_ratio(returns, rf), "ci_low": float("nan"),
            "ci_high": float("nan"), "p_positive": float("nan"),
            "n_resamples": 0,
        }

    values = excess.to_numpy()
    rng = np.random.default_rng(seed)
    restart_probability = 1.0 / expected_block

    # Vectorised index construction: at each step either advance one position
    # (continue the block) or jump to a fresh uniform position (start a new one).
    starts = rng.integers(0, n, size=(n_resamples, n))
    restarts = rng.random((n_resamples, n)) < restart_probability
    restarts[:, 0] = True

    indices = np.empty((n_resamples, n), dtype=np.int64)
    indices[:, 0] = starts[:, 0]
    for step in range(1, n):
        advanced = (indices[:, step - 1] + 1) % n
        indices[:, step] = np.where(restarts[:, step], starts[:, step], advanced)

    samples = values[indices]
    means = samples.mean(axis=1)
    stds = samples.std(axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        sharpes = np.where(
            stds > _EPS, means / stds * np.sqrt(TRADING_DAYS_PER_YEAR), np.nan
        )
    sharpes = sharpes[np.isfinite(sharpes)]

    if len(sharpes) == 0:
        return {
            "sharpe": sharpe_ratio(returns, rf), "ci_low": float("nan"),
            "ci_high": float("nan"), "p_positive": float("nan"),
            "n_resamples": 0,
        }

    tail = (1.0 - confidence) / 2.0
    return {
        "sharpe": sharpe_ratio(returns, rf),
        "ci_low": float(np.quantile(sharpes, tail)),
        "ci_high": float(np.quantile(sharpes, 1.0 - tail)),
        "p_positive": float((sharpes > 0).mean()),
        "n_resamples": int(len(sharpes)),
    }


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def summarise(
    returns: pd.Series,
    rf: pd.Series | float | None = None,
    benchmark: pd.Series | None = None,
    turnover: pd.Series | None = None,
) -> dict[str, float]:
    """Compute the project's standard metric set for one return stream.

    Args:
        returns: Strategy daily returns, net of costs.
        rf: Daily risk-free rate.
        benchmark: Benchmark daily returns, for beta/alpha.
        turnover: Per-rebalance turnover, for the annualised figure.

    Returns:
        Flat mapping suitable for a results table row.

    """
    summary: dict[str, float] = {
        "total_return": total_return(returns),
        "ann_return": annualised_return(returns),
        "ann_volatility": annualised_volatility(returns),
        "sharpe": sharpe_ratio(returns, rf),
        "sortino": sortino_ratio(returns, rf),
        "max_drawdown": max_drawdown(returns),
        "calmar": calmar_ratio(returns),
        "hit_rate": hit_rate(returns),
        "profit_factor": profit_factor(returns),
        "n_obs": int(returns.dropna().shape[0]),
    }

    hac = newey_west_tstat(to_excess(returns, rf))
    summary["tstat_nw"] = hac["tstat"]

    if turnover is not None:
        summary["ann_turnover"] = annualised_turnover(
            turnover, n_trading_days=int(returns.dropna().shape[0])
        )

    if benchmark is not None:
        summary.update(
            {f"bm_{k}": v for k, v in beta_alpha(returns, benchmark, rf).items()}
        )

    return summary
