"""Anti-overfitting selection: splits, deflated Sharpe, perturbation, de-dup."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, skew

from src.overfitting import deflated_sharpe_ratio
from src.search.engine import metrics
from src.search.families import Trial

SPLITS = {"train": ("2008-01-01", "2020-12-31"), "valid": ("2021-01-01", "2024-12-31"),
          "hold": ("2025-01-01", None)}


def split_stats(r: pd.Series) -> dict:
    out = {}
    for k, (a, b) in SPLITS.items():
        x = r.loc[a:b].dropna()
        m = metrics(x)
        m["skew"] = float(skew(x)) if len(x) > 2 else 0.0
        m["kurt"] = float(kurtosis(x, fisher=False)) if len(x) > 3 else 3.0
        out[k] = m
    return out


def add_dsr(table: pd.DataFrame) -> pd.DataFrame:
    var = float(np.var(table["valid_sharpe_d"], ddof=1)) if len(table) > 1 else 0.0
    var = max(var, 1e-8)
    table["dsr"] = [deflated_sharpe_ratio(s, int(n), len(table), var, skewness=sk, kurtosis=ku)
                    for s, n, sk, ku in zip(table["valid_sharpe_d"], table["valid_n"],
                                            table["valid_skew"], table["valid_kurt"],
                                            strict=True)]
    return table


def perturb(trial: Trial) -> list[Trial]:
    out = []
    for k, v in trial.params.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        for f in (0.8, 1.2):
            nv = type(v)(round(v * f)) if isinstance(v, int) else v * f
            if nv == v:
                continue
            p = dict(trial.params, **{k: nv})
            out.append(Trial(f"{trial.name}|{k}x{f}", trial.family, p))
    return out


def dedup(returns: dict, order: list[str], max_corr: float = 0.9) -> list[str]:
    keep = []
    for n in order:
        if all(abs(returns[n].corr(returns[k])) <= max_corr for k in keep):
            keep.append(n)
    return keep
