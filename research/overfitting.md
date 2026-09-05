# Overfitting, multiple testing, and the H1 result

**Last updated:** 2026-09-05 · **Period:** TRAIN only (2007-01-03 → 2016-12-30)
**Test period untouched.**

---

## Summary

**H1 (cross-sectional momentum) is REJECTED** by the rejection rule
pre-registered in `research/hypotheses.md` §H5, before any result was seen.

It is rejected not because it lost money — it returned 7.49% annually net of
10 bps — but because it **fails to beat simple diversification across most of
its own parameter space**, and because its Sharpe confidence interval includes
zero.

This document records how that conclusion was reached, and what a careless
version of the same analysis would have reported instead.

---

## 1. The headline specification

Run at H1's **pre-registered primary parameters** — lookback 126, skip 21,
top-5, monthly, equal weight — fixed in `hypotheses.md` before any backtest
existed.

| Cost | Ann. return | Ann. vol | Sharpe | Max DD | Turnover | Beta | Alpha | t (NW) |
|---|---|---|---|---|---|---|---|---|
| 0 bps | 8.17% | 16.94% | 0.509 | −39.7% | 6.34× | 0.62 | +3.56% | 1.86 |
| 5 bps | 7.83% | 16.94% | 0.491 | −39.7% | 6.34× | 0.62 | +3.24% | 1.80 |
| **10 bps** | **7.49%** | **16.94%** | **0.472** | **−39.8%** | **6.34×** | **0.62** | **+2.93%** | **1.73** |
| 20 bps | 6.81% | 16.94% | 0.434 | −40.0% | 6.34× | 0.62 | +2.29% | 1.59 |

Benchmarks over the same period, net of 10 bps:

| Benchmark | Sharpe | Ann. return | Vol | Max DD |
|---|---|---|---|---|
| Equal-weight 16 ETFs, monthly | **0.486** | 7.82% | 17.16% | −45.4% |
| 60/40 SPY-TLT, monthly | **0.668** | 7.59% | 10.85% | −31.2% |

**H1 at its pre-registered specification underperforms equal-weighting**
(0.472 vs 0.486) and is far behind 60/40 (0.668).

### Bootstrap interval

Stationary bootstrap, 5,000 resamples, expected block 21 days:

> Sharpe **0.472**, 95% CI **[−0.088, 1.088]**, P(Sharpe > 0) = **0.949**

The interval **includes zero**. Under the pre-registered decision rule — "a
hypothesis is supported only if the net-of-10bps Sharpe CI excludes zero" — H1
fails at the first criterion. Note also how wide the interval is: ±0.59 around
a point estimate of 0.47. Ten years of daily data does not pin down a Sharpe
ratio.

---

## 2. Where my pre-registered prior was wrong

I recorded this prediction in `hypotheses.md` before running anything:

> "I expect a positive gross Sharpe and **substantial degradation after
> costs**, because a 16-asset universe forces large discrete weight changes
> when a single name enters or leaves the top 5."

**The turnover half was right. The cost-impact half was wrong.**

Turnover came in at **6.34× annually** — very high, as predicted, and consistent
with swapping one to two of five positions each month. But the Sharpe damage
from costs was modest: 0.509 gross → 0.472 net at 10 bps, a decline of about
7%. That is not "substantial degradation."

The arithmetic reconciles: 6.34 × 10 bps = 63 bps per year of cost, against an
8.17% gross return. Painful but not fatal.

**So H1 does not fail for the reason I expected.** It fails because the signal
does not earn its keep against simple diversification — a different and more
interesting failure, discussed in §4. Recording the wrong prediction alongside
the right one is the point of pre-registration; a prior that is never checked
is not a prior.

---

## 3. Multiple testing: the number a careless report would quote

**50 configurations** were evaluated: lookback ∈ {21, 63, 126, 189, 252} ×
top-k ∈ {3, 4, 5, 6, 8} × skip ∈ {0, 21}. Every one is counted here, as
required by `hypotheses.md`.

| Statistic | Sharpe |
|---|---|
| **Best** configuration (63 / k=8 / skip=0) | **0.626** |
| **Median** configuration | **0.458** |
| Worst configuration | 0.218 |
| Standard deviation across the grid | 0.098 |
| Equal-weight benchmark | 0.486 |

**Configurations beating the benchmark: 18 of 50 = 36.0%.**
**Pre-registered threshold: 60%. → REJECTED.**

### The gap is the entire lesson

A report written without this discipline would say:

> *"Cross-sectional momentum achieved a Sharpe ratio of 0.63, outperforming an
> equal-weight benchmark at 0.49."*

Every number in that sentence is arithmetically correct. The sentence is still
false as a claim about the strategy, because 0.63 is the **maximum of 50
trials**, and the median trial returns 0.458 — *below* the benchmark. Choosing
lookback=63, k=8, skip=0 after seeing the results is not a finding; it is
selection.

The pre-registered specification (126/5/21) scored 0.472 — near the middle of
the grid. Pre-registration is what stopped 0.626 from becoming the headline.

---

## 4. Why it fails: the diagnostic that matters

Sharpe by top-k, median across all lookbacks and skips:

| top-k | Median Sharpe |
|---|---|
| 3 | 0.350 |
| 4 | 0.446 |
| 5 | 0.463 |
| 6 | 0.499 |
| 8 | **0.542** |
| *(16 = equal weight)* | *0.486 benchmark* |

**Sharpe rises monotonically as the portfolio becomes less concentrated.**

This is the most informative single result in the analysis. If the momentum
signal carried genuine information about which assets will outperform, then
concentrating into the highest-ranked names should *help* — a top-3 portfolio
should beat a top-8 portfolio, because it holds more of what the signal likes.

The opposite happens. Performance improves the more the signal's opinion is
diluted. **The gains are coming from diversification, not from ranking.** The
strategy is best when it does the least selecting.

That is a mechanistic explanation of the failure, not just an observation that
it failed — and it generalises: it predicts that any further tuning of the
*signal* is unlikely to help, which is a testable claim that H4 (portfolio
construction) will address directly.

### The skip result contradicts the textbook

| skip | Median Sharpe |
|---|---|
| 0 | **0.483** |
| 21 | 0.443 |

The canonical momentum specification skips the most recent month, because
short-horizon reversal contaminates the signal. Here the skip **hurts**.

A plausible mechanism, offered as a hypothesis rather than a conclusion:
short-term reversal is largely a *single-stock* phenomenon, driven by bid-ask
bounce and idiosyncratic overreaction. These are diversified baskets, so there
is little idiosyncratic reversal to avoid — and skipping a month discards a
month of genuine trend information for no compensating benefit.

This is testable on single-name data and is logged as future work rather than
asserted. It could also simply be noise: the difference is 0.04 of Sharpe on a
grid whose standard deviation is 0.098.

---

## 5. What survives

Not everything here is negative, and the positives should be stated as
carefully as the negatives:

- H1 had **lower beta** (0.62) than equal-weight (0.80) and a **smaller
  drawdown** (−39.8% vs −45.4%).
- It produced **positive alpha versus SPY** of +2.93%/yr at 10 bps.

But 60/40 achieved a *higher* alpha (+3.57%) at a *lower* beta (0.45), so H1
is not the best available way to obtain that exposure — and none of these
t-statistics reaches 2.0 anyway.

---

## 6. Calibration: what "significant" would even require

From the benchmark run, over the same ten years and 2,518 observations:

| Portfolio | t-stat (Newey-West) |
|---|---|
| SPY buy & hold | 1.54 |
| Equal-weight 16 | 1.83 |
| 60/40 SPY-TLT | 2.32 |
| **H1 momentum @ 10 bps** | **1.73** |

**A decade of S&P 500 returns does not reach t = 2.** This is the context in
which every other number in this project must be read. It is also why the live
paper-trading period — roughly 65–85 trading days — is reported as evidence of
**execution capability**, never of performance. At that sample size the
standard error on a Sharpe ratio is larger than any plausible Sharpe.

---

## 7. Consequences for the project

1. **H1 is rejected and stays rejected.** It will not be re-run with different
   parameters to obtain a better number. The rejection rule was set in advance
   precisely so it would bind when inconvenient.
2. **The `top_k` monotonicity result reframes the remaining work.** If
   dilution helps and selection hurts, then the secondary research question —
   does portfolio *construction* contribute more reliably than signal tuning? —
   now has direct supporting evidence, before H4 has even been run.
3. **The trial count carries forward.** 50 configurations are on the ledger.
   Any future best-in-sample figure must be reported against the running total.
4. **H2 and H3 are unaffected** and proceed as pre-registered.

---

## Reproducing

```bash
PYTHONPATH=. python scripts/run_h1.py        # headline + cost sweep + bootstrap
PYTHONPATH=. python scripts/run_h1_grid.py   # 50-configuration stability grid
```

Both read TRAIN data only. The test period is not accessed by either script.
