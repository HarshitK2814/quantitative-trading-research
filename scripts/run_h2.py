"""H2: time-series (absolute) momentum / trend following, TRAIN period only.

Pre-registered primary spec (research/hypotheses.md, committed 2026-09-05
before any backtest): lookback 252, monthly rebalance, equal weight among
qualifying assets, risk-free hurdle. Unallocated capital sits in cash.

H2's pre-registration makes two demands this script must satisfy, not just
report around:

1. **The stated prior** is that any Sharpe improvement comes from the
   *denominator* (lower volatility and drawdown), not the numerator. So
   volatility and drawdown are reported as first-class results, not
   afterthoughts.
2. **A specific falsification test:** "if H2's advantage over H1 is
   concentrated in 2008-09 and March 2020, it is a crisis-alpha strategy whose
   expected benefit depends on crises recurring -- not a general-purpose
   improvement. This must be checked by excluding those windows and
   re-measuring." The train window contains 2008-09; that exclusion is run
   below.

H2 has also become the comparison arm for H9's live options hedge (see
research/institutional_landscape.md §6 and daily_log findings #29-30): AQR's
published evidence is that trend-following outperforms put-buying as crisis
protection. That raises the stakes of this backtest but changes none of its
pre-registered terms.
"""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from src.backtest import buy_and_hold, run_backtest
from src.config import COSTS, SPLITS, UNIVERSE
from src.data import align_risk_free, load_prices, load_risk_free_rate
from src.metrics import bootstrap_sharpe_ci, max_drawdown, sharpe_ratio, summarise
from src.signals import cross_sectional_momentum, time_series_trend

logging.basicConfig(level=logging.ERROR)
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 40)

prices = load_prices(UNIVERSE, SPLITS.history_start, date.today())
rf_raw = load_risk_free_rate(SPLITS.history_start, date.today())

train = prices.loc[str(SPLITS.train_start): str(SPLITS.train_end)]
rf = align_risk_free(rf_raw, train.index)
spy = train["SPY"].pct_change().fillna(0.0)

weights = time_series_trend(train, rf_daily=rf)  # pre-registered defaults

print("=" * 112)
print(f"H2 TIME-SERIES TREND  |  TRAIN ONLY {train.index.min().date()} .. "
      f"{train.index.max().date()}")
print("Pre-registered spec: lookback=252, monthly, equal weight, risk-free hurdle")
print("=" * 112)

# ---------------------------------------------------------------------------
# 1. Cost sweep + benchmarks
# ---------------------------------------------------------------------------
rows = {}
for bps in COSTS.sweep_bps:
    result = run_backtest(train, weights, cost_bps=bps, rf_daily=rf)
    stats = summarise(result.returns, rf=rf, benchmark=spy, turnover=result.turnover)
    stats["rebalances"] = len(result.rebalance_dates)
    rows[f"H2 {bps:.0f} bps"] = stats

# H1 at the same cost, as the direct comparison
h1_weights = cross_sectional_momentum(train)
h1 = run_backtest(train, h1_weights, cost_bps=10.0, rf_daily=rf)
rows["H1 momentum 10bps"] = summarise(h1.returns, rf=rf, benchmark=spy,
                                      turnover=h1.turnover)

ew = buy_and_hold(train, {t: 1 / len(UNIVERSE) for t in UNIVERSE},
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

# ---------------------------------------------------------------------------
# 2. Headline significance
# ---------------------------------------------------------------------------
headline = run_backtest(train, weights, cost_bps=10.0, rf_daily=rf)
ci = bootstrap_sharpe_ci(headline.returns, rf=rf, n_resamples=5000)
print()
print("Headline (10bps) stationary-bootstrap Sharpe CI, 5000 resamples:")
print(f"  Sharpe {ci['sharpe']:.4f}   95% CI [{ci['ci_low']:.4f}, {ci['ci_high']:.4f}]"
      f"   P(Sharpe>0) = {ci['p_positive']:.3f}")

# ---------------------------------------------------------------------------
# 3. THE PRE-REGISTERED PRIOR: is the gain in the denominator?
# ---------------------------------------------------------------------------
print()
print("-" * 112)
print("PRE-REGISTERED PRIOR CHECK: 'improvement comes from the denominator,")
print("not the numerator' -- i.e. lower vol/drawdown rather than higher return.")
print("-" * 112)
h2_s = table.loc["H2 10 bps"]
ew_s = table.loc["BENCH: EW 10bps"]
ret_v = "BETTER" if h2_s["ann_return"] > ew_s["ann_return"] else "WORSE"
vol_v = "BETTER" if h2_s["ann_volatility"] < ew_s["ann_volatility"] else "WORSE"
dd_v = "BETTER" if h2_s["max_drawdown"] > ew_s["max_drawdown"] else "WORSE"
print(f"  Ann return   H2 {h2_s['ann_return']:+.4f}  vs  EW "
      f"{ew_s['ann_return']:+.4f}   -> numerator {ret_v}")
print(f"  Ann vol      H2 {h2_s['ann_volatility']:.4f}  vs  EW "
      f"{ew_s['ann_volatility']:.4f}   -> denominator {vol_v}")
print(f"  Max drawdown H2 {h2_s['max_drawdown']:.4f}  vs  EW "
      f"{ew_s['max_drawdown']:.4f}   -> {dd_v}")

# ---------------------------------------------------------------------------
# 4. THE PRE-REGISTERED FALSIFICATION TEST: exclude the crisis window
# ---------------------------------------------------------------------------
print()
print("-" * 112)
print("PRE-REGISTERED FALSIFICATION TEST: exclude 2008-09 and re-measure.")
print("If H2's edge over H1/EW lives only in the crisis, it is crisis alpha,")
print("not a general-purpose improvement -- and must be described that way.")
print("-" * 112)

crisis = ((headline.returns.index >= "2008-01-01")
          & (headline.returns.index <= "2009-12-31"))
h2_ret, h1_ret, ew_ret = headline.returns, h1.returns, ew.returns

for label, mask in (("FULL train", slice(None)),
                    ("CRISIS 2008-09 only", crisis),
                    ("EX-CRISIS (2008-09 removed)", ~crisis)):
    h2_sub = h2_ret[mask] if label != "FULL train" else h2_ret
    h1_sub = h1_ret[mask] if label != "FULL train" else h1_ret
    ew_sub = ew_ret[mask] if label != "FULL train" else ew_ret
    rf_sub = rf.reindex(h2_sub.index)
    print(f"  {label:30}  H2 Sharpe {sharpe_ratio(h2_sub, rf=rf_sub):+.4f}"
          f"   H1 {sharpe_ratio(h1_sub, rf=rf_sub):+.4f}"
          f"   EW {sharpe_ratio(ew_sub, rf=rf_sub):+.4f}"
          f"   | H2 maxDD {max_drawdown(h2_sub):.4f}"
          f"  EW maxDD {max_drawdown(ew_sub):.4f}")

# ---------------------------------------------------------------------------
# 5. H5 GRID STABILITY -- the pre-declared 60% rejection rule
# ---------------------------------------------------------------------------
print()
print("-" * 112)
print("H5 PARAMETER STABILITY: pre-declared rule -- REJECT if fewer than 60% of")
print("grid configurations beat the equal-weight benchmark net of 10bps.")
print("-" * 112)

bench_sharpe = float(table.loc["BENCH: EW 10bps", "sharpe"])
grid_rows = []
for lookback in (63, 126, 189, 252):
    for rebal in ("ME", "W-FRI"):
        w = time_series_trend(train, lookback=lookback, rebalance=rebal, rf_daily=rf)
        r = run_backtest(train, w, cost_bps=10.0, rf_daily=rf)
        s = summarise(r.returns, rf=rf, benchmark=spy, turnover=r.turnover)
        grid_rows.append({
            "lookback": lookback, "rebalance": rebal,
            "sharpe": s["sharpe"], "ann_return": s["ann_return"],
            "ann_vol": s["ann_volatility"], "max_dd": s["max_drawdown"],
            "turnover": s["ann_turnover"],
            "beats_bench": s["sharpe"] > bench_sharpe,
        })

grid = pd.DataFrame(grid_rows)
print(grid.round(4).to_string(index=False))
frac = grid["beats_bench"].mean()
print()
print(f"  Benchmark (EW 10bps) Sharpe : {bench_sharpe:.4f}")
print(f"  Grid configurations         : {len(grid)}")
print(f"  Best grid Sharpe            : {grid['sharpe'].max():.4f}")
print(f"  MEDIAN grid Sharpe          : {grid['sharpe'].median():.4f}  <- judged on")
print(f"  Fraction beating benchmark  : {frac:.1%}  (pre-declared threshold 60%)")
print()
verdict = ("SUPPORTED on TRAIN (passes H5 stability rule)" if frac >= 0.60
           else "REJECTED by the pre-registered H5 rule")
print(f"  ==> H2 VERDICT: {verdict}")
# ---------------------------------------------------------------------------
# 6. VALIDATION PERIOD -- legitimate to consult; only TEST is one-touch
# ---------------------------------------------------------------------------
print()
print("=" * 112)
print("VALIDATION PERIOD 2017-2020 -- consulted because only the TEST period")
print("(2021-2025) is subject to the one-touch rule.")
print("=" * 112)

val = prices.loc[str(SPLITS.validation_start): str(SPLITS.validation_end)]
rf_v = align_risk_free(rf_raw, val.index)
spy_v = val["SPY"].pct_change().fillna(0.0)

v_rows = {}
v_w = time_series_trend(val, rf_daily=rf_v)
v_h2 = run_backtest(val, v_w, cost_bps=10.0, rf_daily=rf_v)
v_rows["H2 trend 10bps"] = summarise(v_h2.returns, rf=rf_v, benchmark=spy_v,
                                     turnover=v_h2.turnover)
v_h1w = cross_sectional_momentum(val)
v_h1 = run_backtest(val, v_h1w, cost_bps=10.0, rf_daily=rf_v)
v_rows["H1 momentum 10bps"] = summarise(v_h1.returns, rf=rf_v, benchmark=spy_v,
                                        turnover=v_h1.turnover)
v_ew = buy_and_hold(val, {t: 1 / len(UNIVERSE) for t in UNIVERSE}, rebalance="ME",
                    cost_bps=10.0, rf_daily=rf_v)
v_rows["BENCH: EW 10bps"] = summarise(v_ew.returns, rf=rf_v, benchmark=spy_v,
                                      turnover=v_ew.turnover)
v_sf = buy_and_hold(val, {"SPY": 0.6, "TLT": 0.4}, rebalance="ME", cost_bps=10.0,
                    rf_daily=rf_v)
v_rows["BENCH: 60/40 10bps"] = summarise(v_sf.returns, rf=rf_v, benchmark=spy_v,
                                         turnover=v_sf.turnover)

v_table = pd.DataFrame(v_rows).T
print()
print(v_table[cols].round(4).to_string())

v_ci = bootstrap_sharpe_ci(v_h2.returns, rf=rf_v, n_resamples=5000)
print()
print(f"H2 validation Sharpe {v_ci['sharpe']:.4f}  95% CI "
      f"[{v_ci['ci_low']:.4f}, {v_ci['ci_high']:.4f}]  "
      f"P(Sharpe>0) = {v_ci['p_positive']:.3f}")

# The decisive test: did the crisis hedge actually work in the validation
# period's one real crisis? Train's crisis (2008-09) was slow-rolling; COVID
# was fast. A monthly-rebalanced 252-day filter can only react at one speed.
print()
print("-" * 112)
print("COVID CRASH 2020-02-15 .. 2020-04-15, cumulative return:")
print("(the validation period's only severe drawdown -- and a FAST one, unlike")
print(" the slow-rolling 2008-09 decline the train-period result was built on)")
print("-" * 112)
covid = ((v_h2.returns.index >= "2020-02-15")
         & (v_h2.returns.index <= "2020-04-15"))
for lbl, ser in (("H2 trend", v_h2.returns), ("H1 momentum", v_h1.returns),
                 ("EW bench", v_ew.returns), ("60/40", v_sf.returns)):
    print(f"  {lbl:14} {(1 + ser[covid]).prod() - 1:+.4%}")

print()
print("Reminder: the test period (2021-2025) remains untouched and stays that")
print("way until a strategy is frozen and committed.")
