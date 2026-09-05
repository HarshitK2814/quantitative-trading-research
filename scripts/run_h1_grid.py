"""H5 parameter-stability grid for H1. TRAIN only.

Pre-registered rejection rule (research/hypotheses.md H5): a strategy is
rejected if fewer than 60% of its grid configurations beat the equal-weight
benchmark net of 10bps -- regardless of peak performance.
"""
from __future__ import annotations

import itertools
import logging
from datetime import date

import pandas as pd

from src.backtest import buy_and_hold, run_backtest
from src.config import SPLITS, UNIVERSE
from src.data import align_risk_free, load_prices, load_risk_free_rate
from src.metrics import sharpe_ratio
from src.signals import cross_sectional_momentum

logging.basicConfig(level=logging.ERROR)
pd.set_option("display.width", 240)

prices = load_prices(UNIVERSE, SPLITS.history_start, date.today())
rf_raw = load_risk_free_rate(SPLITS.history_start, date.today())
train = prices.loc[str(SPLITS.train_start): str(SPLITS.train_end)]
rf = align_risk_free(rf_raw, train.index)

bench = buy_and_hold(train, {t: 1/len(UNIVERSE) for t in UNIVERSE},
                     rebalance="ME", cost_bps=10.0, rf_daily=rf)
bench_sharpe = sharpe_ratio(bench.returns, rf=rf)

LOOKBACKS = [21, 63, 126, 189, 252]
TOP_K = [3, 4, 5, 6, 8]
SKIPS = [0, 21]

records = []
for lookback, k, skip in itertools.product(LOOKBACKS, TOP_K, SKIPS):
    w = cross_sectional_momentum(train, lookback=lookback, skip=skip, top_k=k)
    r = run_backtest(train, w, cost_bps=10.0, rf_daily=rf)
    records.append({
        "lookback": lookback, "top_k": k, "skip": skip,
        "sharpe": sharpe_ratio(r.returns, rf=rf),
    })

grid = pd.DataFrame(records)
n = len(grid)
beat = (grid.sharpe > bench_sharpe).sum()

print("=" * 88)
print(f"H1 PARAMETER STABILITY GRID  |  TRAIN ONLY  |  {n} configurations tested")
print("=" * 88)
print(f"Equal-weight benchmark Sharpe (net 10bps): {bench_sharpe:.4f}")
print()
print(f"  Best   grid Sharpe : {grid.sharpe.max():.4f}")
print(f"  MEDIAN grid Sharpe : {grid.sharpe.median():.4f}   <- the honest number")
print(f"  Worst  grid Sharpe : {grid.sharpe.min():.4f}")
print(f"  Std dev            : {grid.sharpe.std():.4f}")
print()
print(f"  Configurations beating benchmark: {beat}/{n} = {100*beat/n:.1f}%")
print("  Pre-registered threshold        : 60.0%")
print(f"  VERDICT: {'PASS' if 100*beat/n >= 60 else 'REJECTED'}")
print()
print("Sharpe by lookback (median across k and skip):")
print(grid.groupby("lookback").sharpe.median().round(4).to_string())
print()
print("Sharpe by top_k (median across lookback and skip):")
print(grid.groupby("top_k").sharpe.median().round(4).to_string())
print()
print("Sharpe by skip (median):")
print(grid.groupby("skip").sharpe.median().round(4).to_string())
print()
print("Top 5 configurations (the ones a careless report would quote):")
print(grid.nlargest(5, "sharpe").round(4).to_string(index=False))
