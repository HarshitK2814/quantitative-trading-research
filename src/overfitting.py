"""Multiple-testing correction for Sharpe ratios.

Implements the Deflated Sharpe Ratio of Bailey & Lopez de Prado (2014). It
answers: given that N configurations were tried and their Sharpes had variance
V, what is the probability that this candidate's true Sharpe exceeds the best
one expects from luck alone? All Sharpes are **per-period** (not annualised).
"""

from __future__ import annotations

from math import e, sqrt

from scipy.stats import norm

EULER_GAMMA = 0.5772156649015329


def expected_max_sharpe(n_trials: int, sharpe_variance: float) -> float:
    """Return the expected maximum Sharpe among ``n_trials`` skill-less trials."""
    if n_trials < 2 or sharpe_variance <= 0:
        return 0.0
    return sqrt(sharpe_variance) * (
        (1.0 - EULER_GAMMA) * norm.ppf(1.0 - 1.0 / n_trials)
        + EULER_GAMMA * norm.ppf(1.0 - 1.0 / (n_trials * e))
    )


def deflated_sharpe_ratio(
    sharpe: float,
    n_obs: int,
    n_trials: int,
    sharpe_variance: float,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Probability the candidate's Sharpe beats the luck-only expected maximum."""
    benchmark = expected_max_sharpe(n_trials, sharpe_variance)
    variance_term = 1.0 - skewness * sharpe + (kurtosis - 1.0) / 4.0 * sharpe**2
    if n_obs < 2 or variance_term <= 0:
        return float("nan")
    z = (sharpe - benchmark) * sqrt(n_obs - 1) / sqrt(variance_term)
    return float(norm.cdf(z))
