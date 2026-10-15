"""H14: risk-based position sizing (ERC, HRP) on H1's selected assets."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform
from sklearn.covariance import LedoitWolf

from src.features import DEFAULT_SIGNAL_LAG


def erc_weights(cov: np.ndarray, iters: int = 500, tol: float = 1e-12) -> np.ndarray:
    """Equal-risk-contribution weights by cyclical coordinate descent."""
    n = cov.shape[0]
    w = np.full(n, 1.0 / n)
    c = 1.0 / n
    for _ in range(iters):
        prev = w.copy()
        for i in range(n):
            b = float(cov[i] @ w - cov[i, i] * w[i])
            w[i] = (-b + np.sqrt(b * b + 4.0 * cov[i, i] * c)) / (2.0 * cov[i, i])
        if np.abs(w - prev).max() < tol:
            break
    return w / w.sum()


def _cluster_var(cov: np.ndarray, idx: list[int]) -> float:
    sub = cov[np.ix_(idx, idx)]
    ivp = 1.0 / np.diag(sub)
    ivp = ivp / ivp.sum()
    return float(ivp @ sub @ ivp)


def hrp_weights(cov: np.ndarray) -> np.ndarray:
    """Hierarchical risk parity (Lopez de Prado 2016)."""
    n = cov.shape[0]
    if n == 1:
        return np.ones(1)
    sd = np.sqrt(np.diag(cov))
    corr = np.clip(cov / np.outer(sd, sd), -1.0, 1.0)
    dist = np.sqrt((1.0 - corr) / 2.0)
    np.fill_diagonal(dist, 0.0)
    link = linkage(squareform(dist, checks=False), method="single")

    # quasi-diagonalisation
    order = [int(link[-1, 0]), int(link[-1, 1])]
    while max(order) >= n:
        expanded: list[int] = []
        for item in order:
            if item >= n:
                row = link[item - n]
                expanded += [int(row[0]), int(row[1])]
            else:
                expanded.append(item)
        order = expanded

    w = np.ones(n)
    groups = [order]
    while groups:
        groups = [g[i:j] for g in groups if len(g) > 1
                  for i, j in ((0, len(g) // 2), (len(g) // 2, len(g)))]
        for k in range(0, len(groups), 2):
            left, right = groups[k], groups[k + 1]
            vl, vr = _cluster_var(cov, left), _cluster_var(cov, right)
            alpha = 1.0 - vl / (vl + vr)
            w[left] *= alpha
            w[right] *= 1.0 - alpha
    return w / w.sum()


def apply_risk_construction(
    weights: pd.DataFrame,
    prices: pd.DataFrame,
    method: Literal["erc", "hrp"],
    cov_window: int = 252,
    max_weight: float = 0.25,
    lag: int = DEFAULT_SIGNAL_LAG,
) -> pd.DataFrame:
    """Re-size H1's selection by ERC/HRP on a Ledoit-Wolf covariance.

    The covariance uses daily returns ending ``lag`` bars before the
    rebalance date. Weights are capped at ``max_weight``; the remainder is
    cash. Rows with insufficient or missing history become NaN (no trade).
    """
    returns = prices.pct_change(fill_method=None)
    positions = {d: i for i, d in enumerate(prices.index)}
    out = weights.copy()
    for when in weights.dropna(how="all").index:
        sel = weights.loc[when]
        held = list(sel[sel > 0].index)
        end = positions[when] - lag + 1
        start = end - cov_window
        window = returns.iloc[start:end][held] if start >= 1 else None
        if window is None or window.isna().any().any() or len(held) == 0:
            out.loc[when] = np.nan
            continue
        cov = LedoitWolf().fit(window.to_numpy()).covariance_
        alloc = erc_weights(cov) if method == "erc" else hrp_weights(cov)
        alloc = np.minimum(alloc, max_weight)
        row = pd.Series(0.0, index=weights.columns)
        row.loc[held] = alloc
        out.loc[when] = row.to_numpy()
    return out
