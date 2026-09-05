# Pre-registered hypotheses

**Written:** 2026-09-05
**Status:** PRE-REGISTRATION — written before any strategy code was executed.

> **Amendment rule.** Nothing above the `AMENDMENTS` section at the bottom may
> be edited once committed. If a hypothesis changes after results are seen, the
> change is appended below as a dated, explicitly-labelled **post-hoc**
> hypothesis. Post-hoc hypotheses are legitimate research objects, but they are
> never reported as if they had been specified in advance. The git history of
> this file is part of the evidence.

---

## Shared experimental design

Applies to every hypothesis unless overridden.

| Element | Specification |
|---|---|
| **Universe** | 16 fixed ETFs: SPY QQQ IWM DIA XLK XLF XLE XLV XLI XLP XLY XLU VNQ GLD SLV TLT. Fixed ex ante; see `PROJECT_PLAN.md` §4. |
| **Data** | Daily adjusted OHLCV. Primary: yfinance. Cross-check: Stooq. Risk-free: FRED `DTB3`. |
| **Sample** | Train 2007-01-01→2016-12-31 · Validation 2017-01-01→2020-12-31 · Test 2021-01-01→2025-12-31 (one touch only). |
| **Signal timing** | Features from data through close of day *t*; weights apply from day *t+1*. Enforced by a one-bar shift and verified by `tests/test_no_lookahead.py`. |
| **Execution assumption** | Trade at next open. Sensitivity: trade at next close. |
| **Rebalance** | Monthly (last trading day), unless a hypothesis states otherwise. Weekly tested as a sensitivity. |
| **Costs** | Swept at 0 / 5 / 10 / 20 bps per unit turnover. **10 bps is the headline case.** 0 bps is diagnostic only and never reported alone. |
| **Position limits** | Long-only, no leverage, max 25% in any single ETF, weights sum to ≤ 1.0 (remainder in cash at the risk-free rate). |
| **Benchmarks** | SPY buy-and-hold · equal-weight all-16 rebalanced monthly · 60/40 SPY/TLT. |
| **Primary metric** | Annualised Sharpe ratio, net of 10 bps costs, excess of `DTB3`, computed from daily returns and annualised by √252. |
| **Secondary metrics** | Ann. return, ann. vol, max drawdown, Calmar, Sortino, turnover, avg holding period, hit rate, beta and alpha vs SPY, correlation to SPY. |
| **Significance** | Newey–West-adjusted t-statistic on mean daily excess return (lag = 21) plus a stationary-bootstrap 95% CI on the Sharpe ratio (10,000 resamples, expected block length 21 days). |
| **Decision threshold** | A hypothesis is "supported" only if the net-of-10bps Sharpe CI excludes zero **and** the result survives the parameter-stability test in §H5. |

### Multiple-testing accounting

Every parameter configuration evaluated is counted in
`research/overfitting.md`. Reported best-in-sample Sharpe ratios are assessed
against the number of trials that produced them. A configuration count is a
required field in every results table — an unreported trial count makes a
maximum Sharpe uninterpretable.

---

## H1 — Cross-sectional momentum

**Research question.** Does ranking a fixed universe of liquid ETFs on trailing
return, and holding the top *k*, generate risk-adjusted returns that survive
realistic transaction costs?

- **H0:** The net-of-cost Sharpe of the top-*k* momentum portfolio is less than
  or equal to that of the equal-weight benchmark. Any excess is attributable to
  chance and to cost-model optimism.
- **H1:** The net-of-cost Sharpe exceeds the equal-weight benchmark by a margin
  whose bootstrap 95% CI excludes zero.

| Element | Specification |
|---|---|
| Signal | Trailing total return over lookback *L*, skipping the most recent 21 days (standard reversal skip). |
| Primary parameters | *L* = 126 trading days; *k* = 5; monthly rebalance. |
| Sensitivity grid | *L* ∈ {21, 63, 126, 189, 252}; *k* ∈ {3, 4, 5, 6, 8}; skip ∈ {0, 21}. |
| Weighting | Equal-weight the selected *k*. Inverse-vol weighting tested under H4, not here — this hypothesis isolates the signal. |
| Expected mechanism | Under-reaction to slow-moving information and to persistent flows across sectors/asset classes; documented cross-sectionally in equities and across asset classes. |
| Expected turnover | Moderate; monthly rebalance of a 5-name portfolio. Estimated 150–300% annualised — to be measured, not assumed. |

**Stated prior (before running anything):** I expect a positive gross Sharpe and
**substantial degradation after costs**, because a 16-asset universe forces
large discrete weight changes when a single name enters or leaves the top 5.
The most likely honest outcome is a signal that is real but too expensive at
this universe size. If that is what the data shows, that is the finding.

**Known confound to check:** momentum on this universe may be a repackaged
long-equity-beta bet, since equity ETFs outnumber non-equity ones 12:4 and
equities trended upward through most of the sample. A regression of strategy
returns on SPY is mandatory before any alpha claim.

---

## H2 — Time-series (absolute) momentum / trend following

**Research question.** Does conditioning each asset on its *own* trend — rather
than its rank against peers — improve risk-adjusted returns, principally by
allowing the portfolio to de-risk into cash?

- **H0:** Time-series trend filtering does not improve the net-of-cost Sharpe
  relative to equal-weight buy-and-hold.
- **H1:** It does, and the improvement comes primarily from **drawdown
  reduction** rather than from higher returns.

| Element | Specification |
|---|---|
| Signal | Hold asset *i* only if its trailing *L*-day return exceeds the risk-free return over the same window. Otherwise hold cash. |
| Primary parameters | *L* = 252; monthly rebalance; equal weight among qualifying assets. |
| Sensitivity grid | *L* ∈ {63, 126, 189, 252}; also 10-month SMA rule as an alternative specification. |
| Expected mechanism | Volatility and drawdown clustering: sustained downtrends persist long enough that an exit rule avoids part of the drawdown, at the cost of whipsaw in choppy markets. |

**Stated prior:** the Sharpe improvement will come mostly from the denominator
(lower volatility and drawdown), not the numerator. **The specific test:** if
H2's advantage over H1 is concentrated in 2008–09 and March 2020, it is a
crisis-alpha strategy whose expected benefit depends on crises recurring — not
a general-purpose improvement. This must be checked by excluding those windows
and re-measuring. A trend result that survives only because of two crises should
be described that way.

---

## H3 — Short-horizon mean reversion

**Research question.** Do short-horizon losers in this universe outperform over
the following days, and does any such effect survive costs at realistic turnover?

- **H0:** The net-of-cost Sharpe of a short-horizon reversal portfolio does not
  exceed the equal-weight benchmark.
- **H1:** It does.

| Element | Specification |
|---|---|
| Signal | Rank on trailing 5-day return; hold the bottom *k* (worst performers). |
| Primary parameters | Lookback 5 days; *k* = 5; **weekly** rebalance. |
| Sensitivity grid | Lookback ∈ {2, 3, 5, 10}; *k* ∈ {3, 5, 8}; rebalance ∈ {weekly, monthly}. |
| Expected mechanism | Short-term liquidity provision — being compensated for absorbing selling pressure. |

**Stated prior — I expect this to fail, and it is included because of that.**
The mechanism is liquidity provision, and on the most liquid ETFs in the world
the compensation for providing liquidity should be close to zero. Turnover will
be high. Any gross edge is likely to be consumed by costs.

**Why include a hypothesis I expect to fail.** Three reasons, all methodological:
(1) it tests the *opposite* direction to H1/H2, so the project is not merely
confirming one idea in three forms; (2) a documented failure with a cost-based
diagnosis is stronger evidence of judgment than three successes; (3) if it
*does* work, the prior was wrong in an interesting way and that is worth
knowing. A pre-registered prediction of failure is only meaningful because it
was recorded before the test.

---

## H4 — Risk-based portfolio construction (the secondary research question)

**Research question.** Applied as a layer on top of the best signal from
H1–H3, does risk-based sizing improve realised risk-adjusted performance more
reliably than tuning the signal itself?

- **H0:** Inverse-volatility and volatility-targeted construction do not improve
  the net-of-cost Sharpe versus equal-weighting of the same selected assets.
- **H1:** They do, **and** the improvement is more stable across the parameter
  grid than the improvement obtainable by tuning the signal's own parameters.

| Element | Specification |
|---|---|
| Variants | (a) equal weight [baseline] · (b) inverse-volatility · (c) portfolio volatility targeting to 10% annualised · (d) naive risk parity via equal risk contribution |
| Vol estimator | 63-day trailing realised vol, computed on the same one-bar-shifted panel. Sensitivity: 21 and 126 days; EWMA λ=0.94. |
| Constraints | Long-only, no leverage (scaling caps at 100% invested), max 25% per asset. |
| Comparison metric | Not just Sharpe: the **dispersion of Sharpe across the parameter grid**. A construction method that helps across most of the grid is more valuable than a signal parameter that helps at one point. |

**Stated prior:** risk-based construction will produce a smaller Sharpe
improvement than the best signal tuning, but a far more *stable* one — helping
across most of the grid rather than at an isolated maximum. **If true, that is
the project's most interesting result**, because it says the robust gains live
in portfolio construction rather than in signal search, which is where most
retail effort goes.

**Falsification condition:** if inverse-vol weighting helps only at one vol
window and hurts at others, this hypothesis is rejected and the prior was wrong.

---

## H5 — Parameter stability (a meta-hypothesis applied to all of the above)

**Research question.** Is any observed edge a property of the strategy, or of a
specific parameter choice?

- **H0:** Performance is not robust — Sharpe collapses under moderate parameter
  perturbation, indicating a fitted artefact.
- **H1:** Performance degrades gracefully. The chosen parameters are not an
  isolated peak on the parameter surface.

**Test procedure.** For each candidate strategy, evaluate the full sensitivity
grid and report:

1. The full Sharpe surface (heatmap over the two principal parameters).
2. The **median** grid Sharpe, not the maximum. A strategy is judged on its
   median configuration.
3. The fraction of configurations beating the benchmark.
4. Sharpe under ±50% perturbation of each parameter individually.
5. Subperiod stability: Sharpe by calendar year and by volatility regime.

**Pre-declared rejection rule.** A strategy is rejected regardless of its peak
performance if **fewer than 60% of its grid configurations beat the equal-weight
benchmark net of 10 bps.** This threshold is set now, before any results, and
will not be adjusted afterwards. A single spectacular configuration in an
otherwise failing grid is evidence of overfitting, not of edge.

---

## Final selection

The final strategy is chosen by the weighted rubric in `PROJECT_PLAN.md` §8,
applied to **train + validation only**. The test period is not consulted.

Once selected, the strategy, parameters, cost model, and risk limits are frozen
and committed. **The freeze commit hash is recorded in the final report before
the test period is run.** The out-of-sample test then runs exactly once.

**If the out-of-sample result is poor, it is reported as the result.** No
re-selection, no re-tuning, no quiet substitution of a different strategy. The
credibility of every other number in this project depends on that rule holding
when it is inconvenient.

---

## AMENDMENTS

*(Post-hoc hypotheses and amendments are appended below with dates. Nothing
above this line is edited after commit.)*

None yet.
