"""H1: cross-sectional momentum, TRAIN period only, with the full cost sweep.

Pre-registered primary spec (research/hypotheses.md, committed before any
backtest): lookback 126, skip 21, top_k 5, monthly rebalance, equal weight.
"""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from src.backtest import buy_and_hold, run_backtest
from src.config import COSTS, SPLITS, UNIVERSE
from src.data import align_risk_free, load_prices, load_risk_free_rate
from src.metrics import bootstrap_sharpe_ci, summarise
from src.signals import cross_sectional_momentum

logging.basicConfig(level=logging.ERROR)
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 40)

prices = load_prices(UNIVERSE, SPLITS.history_start, date.today())
rf_raw = load_risk_free_rate(SPLITS.history_start, date.today())

train = prices.loc[str(SPLITS.train_start): str(SPLITS.train_end)]
rf = align_risk_free(rf_raw, train.index)
spy = train["SPY"].pct_change().fillna(0.0)

weights = cross_sectional_momentum(train)  # pre-registered defaults

print("=" * 108)
print(f"H1 CROSS-SECTIONAL MOMENTUM  |  TRAIN ONLY {train.index.min().date()} .. "
      f"{train.index.max().date()}")
print("Pre-registered spec: lookback=126, skip=21, top_k=5, monthly, equal weight")
print("=" * 108)

rows = {}
for bps in COSTS.sweep_bps:
    result = run_backtest(train, weights, cost_bps=bps, rf_daily=rf)
    stats = summarise(result.returns, rf=rf, benchmark=spy, turnover=result.turnover)
    stats["rebalances"] = len(result.rebalance_dates)
    rows[f"{bps:.0f} bps"] = stats

ew = buy_and_hold(train, {t: 1/len(UNIVERSE) for t in UNIVERSE},
                  rebalance="ME", cost_bps=10.0, rf_daily=rf)
rows["BENCH: EW 10bps"] = summarise(ew.returns, rf=rf, benchmark=spy,
                                    turnover=ew.turnover)
sf = buy_and_hold(train, {"SPY": 0.6, "TLT": 0.4}, rebalance="ME",
                  cost_bps=10.0, rf_daily=rf)
rows["BENCH: 60/40 10bps"] = summarise(sf.returns, rf=rf, benchmark=spy,
                                       turnover=sf.turnover)

table = pd.DataFrame(rows).T
cols = ["ann_return", "ann_volatility", "sharpe", "max_drawdown", "calmar",
        "ann_turnover", "bm_beta", "bm_alpha_annual", "tstat_nw"]
print()
print(table[cols].round(4).to_string())

headline = run_backtest(train, weights, cost_bps=10.0, rf_daily=rf)
ci = bootstrap_sharpe_ci(headline.returns, rf=rf, n_resamples=5000)
print()
print("Headline (10bps) stationary-bootstrap Sharpe CI, 5000 resamples:")
print(f"  Sharpe {ci['sharpe']:.4f}   95% CI [{ci['ci_low']:.4f}, {ci['ci_high']:.4f}]"
      f"   P(Sharpe>0) = {ci['p_positive']:.3f}")
gross = run_backtest(train, weights, cost_bps=0.0, rf_daily=rf)
print()
print(f"Cost drag: gross Sharpe {summarise(gross.returns, rf=rf)['sharpe']:.4f} "
      f"-> net@10bps {ci['sharpe']:.4f}")
print(f"Annualised turnover: {table.loc['10 bps','ann_turnover']:.2f}x  "
      f"| rebalances: {int(table.loc['10 bps','rebalances'])}")
