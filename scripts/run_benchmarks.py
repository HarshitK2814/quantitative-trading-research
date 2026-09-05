"""End-to-end pipeline check: benchmark portfolios on the TRAIN period only.

Deliberately benchmarks only. No strategy is fitted and no selection decision is
made here, so this does not consume the one-touch out-of-sample budget. The
test period is not read at all.
"""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from src.backtest import buy_and_hold
from src.config import SPLITS, UNIVERSE
from src.data import align_risk_free, load_prices, load_risk_free_rate
from src.metrics import summarise

logging.basicConfig(level=logging.ERROR)
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)

prices = load_prices(UNIVERSE, SPLITS.history_start, date.today())
rf_raw = load_risk_free_rate(SPLITS.history_start, date.today())

train = prices.loc[str(SPLITS.train_start): str(SPLITS.train_end)]
rf = align_risk_free(rf_raw, train.index)

print("=" * 100)
print(f"TRAIN PERIOD ONLY: {train.index.min().date()} .. {train.index.max().date()}"
      f"  ({len(train)} trading days)")
print("Benchmarks only - no strategy fitted, no selection made.")
print("=" * 100)

spy_only = {"SPY": 1.0}
equal_weight = {t: 1.0 / len(UNIVERSE) for t in UNIVERSE}
sixty_forty = {"SPY": 0.6, "TLT": 0.4}

rows = {}
for label, weights, rebal in [
    ("SPY buy & hold",        spy_only,     None),
    ("Equal-weight 16 (BH)",  equal_weight, None),
    ("Equal-weight 16 (ME)",  equal_weight, "ME"),
    ("60/40 SPY-TLT (ME)",    sixty_forty,  "ME"),
]:
    result = buy_and_hold(train, weights, rebalance=rebal, cost_bps=10.0, rf_daily=rf)
    stats = summarise(result.returns, rf=rf,
                      benchmark=train["SPY"].pct_change().fillna(0.0),
                      turnover=result.turnover)
    stats["rebalances"] = len(result.rebalance_dates)
    stats["total_cost"] = result.costs.sum()
    rows[label] = stats

table = pd.DataFrame(rows).T
show = table[["ann_return", "ann_volatility", "sharpe", "sortino", "max_drawdown",
              "calmar", "ann_turnover", "rebalances", "total_cost", "bm_beta",
              "bm_alpha_annual", "tstat_nw"]]
print()
print(show.round(4).to_string())
print()
print("Note: costs at 10bps per unit turnover. Sharpe is excess of FRED DTB3,")
print("annualised by sqrt(252). Beta/alpha are vs SPY.")
