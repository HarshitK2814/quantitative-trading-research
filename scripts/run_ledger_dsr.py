"""Deflated Sharpe over the logged train-period trial ledger.

    PYTHONPATH=. python scripts/run_ledger_dsr.py

TRAIN ONLY. Trials: H1 grid (5 lookbacks x 5 k x skip {0,21} = 50) and the H4
grid (25 signal configs x 5 constructions = 125), as in scripts/run_h4_h7.py.
"""

from __future__ import annotations

import logging
from datetime import date
from itertools import product
from pathlib import Path

import numpy as np
from scipy.stats import kurtosis, skew

from src.backtest import run_backtest
from src.config import SPLITS, UNIVERSE
from src.data import align_risk_free, load_prices, load_risk_free_rate
from src.metrics import sharpe_ratio
from src.overfitting import deflated_sharpe_ratio, expected_max_sharpe
from src.signals import (
    apply_inverse_volatility,
    apply_volatility_target,
    cross_sectional_momentum,
)

logging.basicConfig(level=logging.ERROR)
LOOKBACKS, KS = (21, 63, 126, 189, 252), (3, 4, 5, 6, 8)
ROOT_252 = np.sqrt(252.0)
OUT = Path("research/deflated_sharpe.md")

end = date.today()
prices = load_prices(UNIVERSE, SPLITS.history_start, end)
train = prices.loc[str(SPLITS.train_start): str(SPLITS.train_end)]
rf = align_risk_free(load_risk_free_rate(SPLITS.history_start, end), train.index)


def trial(weights):
    res = run_backtest(train, weights, cost_bps=10.0, rf_daily=rf)
    return res.returns, sharpe_ratio(res.returns, rf=rf) / ROOT_252


h1_sharpes, primary = [], None
for lb, k, skip in product(LOOKBACKS, KS, (0, 21)):
    returns, sr = trial(cross_sectional_momentum(train, lookback=lb, top_k=k, skip=skip))
    h1_sharpes.append(sr)
    if (lb, k, skip) == (126, 5, 21):
        primary = (returns, sr)

h4_sharpes, best = [], None
for lb, k in product(LOOKBACKS, KS):
    base_w = cross_sectional_momentum(train, lookback=lb, top_k=k)
    base_ret, base_sr = trial(base_w)
    h4_sharpes.append(base_sr)
    variants = {
        f"IV{vw}": apply_inverse_volatility(base_w, train, vol_window=vw)
        for vw in (21, 63, 126)
    }
    variants["VT10"] = apply_volatility_target(base_w, base_ret, target_vol=0.10)
    for name, w in variants.items():
        returns, sr = trial(w)
        h4_sharpes.append(sr)
        if best is None or sr > best[1]:
            best = (returns, sr, f"{name} lb={lb} k={k}")


def report(label, returns, sr, n_trials, sharpes):
    var = float(np.var(sharpes, ddof=1))
    dsr = deflated_sharpe_ratio(
        sr, len(returns), n_trials, var,
        skewness=float(skew(returns)), kurtosis=float(kurtosis(returns, fisher=False)),
    )
    return (
        f"| {label} | {sr * ROOT_252:.3f} | {n_trials} | "
        f"{expected_max_sharpe(n_trials, var) * ROOT_252:.3f} | {dsr:.3f} |"
    )


all_sharpes = h1_sharpes + h4_sharpes
rows = [
    report("H1 primary 126/k5/skip21 vs H1 grid", primary[0], primary[1],
           len(h1_sharpes), h1_sharpes),
    report(f"best H4 train config ({best[2]}) vs H1+H4 ledger", best[0], best[1],
           len(all_sharpes), all_sharpes),
]
text = f"""# Deflated Sharpe over the trial ledger (train 2007-2016, 10 bps)

Method: Bailey & Lopez de Prado (2014). Sharpes annualised for display; the
test statistic uses per-period values. `Luck-only max` is the annualised Sharpe
the best of N skill-less trials is expected to reach given the observed
dispersion of trial Sharpes. DSR is the probability the candidate's true Sharpe
exceeds it (0.95+ would be strong; ~0.5 is indistinguishable from selection).

| Candidate | Sharpe | Trials N | Luck-only max | DSR |
|---|---|---|---|---|
{chr(10).join(rows)}

Caveats: ledger counts only the H1 and H4 grids re-computed here; H2/H3/H6/H7
trials are logged separately in `research/overfitting.md`, so true N is larger
and DSR values here are upper bounds. Train window only.
"""
OUT.write_text(text, encoding="utf-8")
print(text)
