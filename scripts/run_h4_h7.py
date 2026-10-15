"""H4 (risk-based construction) and H7 (extended universe), TRAIN period only.

Specs: research/hypotheses.md (H4 pre-registered 2026-09-05; H7 added 2026-09-10).
Validation (2017-2020) and test (2021-2025) are NOT touched here. Every
configuration evaluated is counted and printed -- see the trial ledger in
research/overfitting.md.

H4 grid: lookback {21,63,126,189,252} x top-k {3,4,5,6,8}, skip=21 (25 signal
configs) x 5 constructions (EW, inverse-vol 21/63/126, vol-target 10%/63d).
Variant (d) equal-risk-contribution is NOT run (no covariance machinery built).
H7 grid: the H1 grid (5 x 5 x skip {0,21} = 50) on the original and extended
universe, over the same window (trimmed to when every ticker has data).
"""

from __future__ import annotations

import logging
from datetime import date
from itertools import product

import numpy as np
import pandas as pd

from src.backtest import buy_and_hold, run_backtest
from src.config import COSTS, SPLITS, UNIVERSE
from src.data import align_risk_free, load_prices, load_risk_free_rate
from src.metrics import sharpe_ratio
from src.signals import (
    apply_inverse_volatility,
    apply_volatility_target,
    cross_sectional_momentum,
)

logging.basicConfig(level=logging.ERROR)
pd.set_option("display.width", 200)

UNIVERSE_EXT = [*UNIVERSE, "EFA", "EEM", "USO", "HYG"]  # per H7
LOOKBACKS, KS = (21, 63, 126, 189, 252), (3, 4, 5, 6, 8)
COST = 10.0  # headline case

end = date.today()
all_prices = load_prices(UNIVERSE_EXT, SPLITS.history_start, end)
first_full = all_prices.dropna().index.min()
train = all_prices.loc[str(first_full.date()): str(SPLITS.train_end)]
rf = align_risk_free(load_risk_free_rate(SPLITS.history_start, end), train.index)
print(f"Train window used: {train.index.min().date()} .. {train.index.max().date()} "
      f"({len(train)} days; start trimmed so all 20 tickers have data)")


def sharpe_of(prices, weights) -> float:
    res = run_backtest(prices, weights, cost_bps=COST, rf_daily=rf)
    return sharpe_ratio(res.returns, rf=rf)


# ------------------------------ H4 ------------------------------------------
orig = train[list(UNIVERSE)]
rows = []
for lb, k in product(LOOKBACKS, KS):
    base_w = cross_sectional_momentum(orig, lookback=lb, top_k=k)
    base = run_backtest(orig, base_w, cost_bps=COST, rf_daily=rf)
    row = {"lookback": lb, "k": k, "EW": sharpe_ratio(base.returns, rf=rf)}
    for vw in (21, 63, 126):
        row[f"IV{vw}"] = sharpe_of(orig, apply_inverse_volatility(
            base_w, orig, vol_window=vw))
    row["VT10"] = sharpe_of(orig, apply_volatility_target(
        base_w, base.returns, target_vol=0.10))
    rows.append(row)
h4 = pd.DataFrame(rows)
variants = ["IV21", "IV63", "IV126", "VT10"]

print("\n" + "=" * 100)
print(f"H4 | {len(h4)} signal configs x 5 constructions = {len(h4) * 5} trials")
print("=" * 100)
summary = pd.DataFrame({
    "median Sharpe": h4[["EW", *variants]].median(),
    "Sharpe std across grid": h4[["EW", *variants]].std(),
    "worst": h4[["EW", *variants]].min(),
    "best": h4[["EW", *variants]].max(),
})
summary["% configs beating EW"] = [np.nan] + [
    float((h4[v] > h4["EW"]).mean() * 100) for v in variants
]
summary["median gain vs EW"] = [np.nan] + [
    float((h4[v] - h4["EW"]).median()) for v in variants
]
print(summary.round(3).to_string())

gains = {v: (h4[v] - h4["EW"]) for v in variants}
helps_all_iv = all((gains[v] > 0).mean() > 0.5 for v in ("IV21", "IV63", "IV126"))
hurts_some_iv = any((gains[v] > 0).mean() < 0.5 for v in ("IV21", "IV63", "IV126"))
print("\nFalsification (inverse-vol helps at only one window, hurts others):",
      "TRIGGERED" if hurts_some_iv and not helps_all_iv else "not triggered")
sig_tune = h4["EW"].max() - h4["EW"].median()
print(f"Signal-tuning headroom (best - median EW Sharpe): {sig_tune:+.3f}")
for v in variants:
    print(f"Construction {v}: median gain {gains[v].median():+.3f}, "
          f"beats EW in {(gains[v] > 0).mean():.0%} of configs")

# ------------------------------ H7 ------------------------------------------
ew_bench = {}
for name, cols in (("orig16", list(UNIVERSE)), ("ext20", UNIVERSE_EXT)):
    px = train[cols]
    ew_bench[name] = sharpe_ratio(buy_and_hold(
        px, {t: 1 / len(cols) for t in cols}, rebalance="ME",
        cost_bps=COST, rf_daily=rf).returns, rf=rf)

h7 = {"orig16": [], "ext20": []}
for lb, k, skip in product(LOOKBACKS, KS, (0, 21)):
    for name, cols in (("orig16", list(UNIVERSE)), ("ext20", UNIVERSE_EXT)):
        px = train[cols]
        h7[name].append(sharpe_of(
            px, cross_sectional_momentum(px, lookback=lb, top_k=k, skip=skip)))

print("\n" + "=" * 100)
print(f"H7 | {2 * len(h7['orig16'])} trials (50 per universe), same window, "
      f"10 bps")
print("=" * 100)
for name in ("orig16", "ext20"):
    s = np.array(h7[name])
    frac = float((s > ew_bench[name]).mean())
    print(f"{name}: EW benchmark Sharpe {ew_bench[name]:.3f} | median config "
          f"{np.median(s):.3f} | best {s.max():.3f} | beat EW: {frac:.0%} "
          f"(pre-registered bar 60%)")
