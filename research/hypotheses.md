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

### H6 — Long/short cross-sectional momentum (added 2026-09-09, post-hoc)

**Context for why this is post-hoc.** This was not in the original five
hypotheses. It is added now, at the user's request, specifically to permit
short exposure and multiple concurrently-deployed strategies. It is labelled
post-hoc, dated, and given the same discipline as H1 rather than being folded
into H1's text, so the git history shows plainly that it was not part of the
original design.

**Research question.** Does adding a short leg on the bottom-*k* of the same
momentum ranking used in H1 improve risk-adjusted returns over H1's long-only
version — and specifically, does it reduce market-beta exposure enough to
justify the added operational complexity and cost of shorting?

- **H0:** The net-of-cost Sharpe of the long/short portfolio does not exceed
  H1's long-only Sharpe by a margin whose bootstrap 95% CI excludes zero, OR
  the long/short book's beta to SPY is not meaningfully lower than H1's.
- **H1 (alternative):** The long/short version achieves comparable or better
  Sharpe than H1 **and** materially lower beta to SPY, i.e. the short leg is
  doing more than just adding cost and noise.

| Element | Specification |
|---|---|
| Signal | Identical to H1: trailing total return, lookback 126, skip 21 days. |
| Construction | Long top *k*=5, short bottom *k*=5, from the same 16-ETF universe. Dollar-neutral: long leg sums to 50% of allocated capital, short leg to -50%, gross = 100% of allocated capital, net ≈ 0%. |
| Primary parameters | Same as H1's primary spec, mirrored to the short side. |
| Sensitivity grid | Same grid as H1 §H1, applied symmetrically to both legs. |
| Rebalance | Monthly, same as H1. |
| Position limits | Max 25% gross in any single name (long or short), same asset-class cap as the existing risk engine, gross ≤ 100% of allocated capital (no leverage on top of the dollar-neutral structure itself). |

**Stated prior (before running anything):** I expect the short leg to add
cost and operational risk without a commensurate Sharpe improvement, because
the bottom-*k* momentum losers in this specific universe (large, liquid
sector/asset-class ETFs) are not obviously mispriced — being a laggard is not
the same as being overpriced, and unlike H3's mean-reversion hypothesis this
isn't even betting on a reversal, just on continued relative underperformance.
The most likely honest outcome is a lower-beta but similar-or-worse-Sharpe
book. If that is what the data shows, that is the finding, not a reason to
retune the spec.

**Disclosed limitation, stated before any test:** Alpaca's **paper** account
simulates short mechanics (margin, fills) but does not charge real borrow
fees, apply hard-to-borrow restrictions, or model the risk of a short being
called away. A backtest or forward test run here will be **optimistic
relative to a real short book** for that reason, and any writeup must say so
explicitly rather than let a live paper Sharpe stand in for what a real
short-selling account would have earned.

**Decision rule for deployment.** This hypothesis must go through the same
sequence H1 did — backtested on train data, checked against H5's grid-median
rejection rule, and only then considered for live capital as its own labelled
sleeve (see `src/sleeves.py`). No live short exposure exists yet. Building
the sleeve mechanism that *could* run it is not the same decision as running
it, and the two are logged separately.

---

### H7 — Extended universe: international equities, energy, credit (added 2026-09-10, post-hoc)

**Context.** Added at the user's request to test whether the original 16-ETF
universe under-diversifies the strategy set. The original `UNIVERSE` constant
in `src/config.py` is **not modified** — every H1-H6 result stays reproducible
against exactly the universe it was tested on. This hypothesis defines its own
`UNIVERSE_EXT` and is evaluated independently; it becomes a candidate for a
live sleeve only if it clears the same bar H1 did.

**Research question.** Does adding international-equity, energy-commodity, and
credit exposure to the existing 16-name universe improve H1's diversification
(lower correlation across selectable names → less concentrated top-*k* picks)
without degrading the Sharpe that made H1 worth testing in the first place?

- **H0:** Running H1's identical signal and construction on the extended
  universe does not improve the fraction of grid configurations beating
  equal-weight benchmark (H5's metric) relative to the original 16-name run.
- **H1 (alternative):** It does, because a broader opportunity set gives the
  ranking more genuinely diversifying choices instead of repeatedly picking
  from a narrower, more mutually-correlated equity-sector set.

| Element | Specification |
|---|---|
| Added tickers | EFA (developed ex-US equity), EEM (emerging-market equity), USO (crude oil, distinct commodity-futures-linked exposure from XLE's equity-sector energy), HYG (high-yield credit, distinct from TLT's treasury duration exposure). |
| `UNIVERSE_EXT` | The original 16 plus these 4 = 20 names. Same data source (yfinance), same one-bar-lag discipline, same cost model. |
| Signal | Identical to H1 — this isolates the effect of the universe, not the signal. |
| Sample caveat | EEM (inception 2003) and HYG (inception 2007) both have shorter live histories than the original universe's 2007 start on some names; USO's structure changed materially after its 2020 negative-oil-price restructuring, which must be checked for and disclosed if it distorts trailing-return signals across that date, not silently included. |

**Stated prior:** I expect a small diversification benefit and a roughly flat
or slightly worse net Sharpe, because more selectable names does not fix H1's
actual diagnosed problem (Sharpe rising with lower concentration, i.e. the
signal itself adding little) — it just gives the same weak signal more places
to pick from. If broadening the universe doesn't change *that* underlying
pattern, this hypothesis should say so plainly rather than be read as "fixing"
H1.

---

### H8 — Crypto time-series momentum (added 2026-09-10, post-hoc)

**Context.** Alpaca's paper account supports crypto trading (BTC, ETH, and
others) under the same credentials as the equity/ETF book — no second broker,
no new cost. Added at the user's request for genuine asset-class diversity
beyond equities/bonds/commodities-via-ETF.

**Research question.** Does H2's time-series (absolute) momentum rule —
already pre-registered, not yet backtested — perform differently on crypto
than on the equity/ETF universe, given crypto's documented higher volatility
and different market-structure (24/7, no circuit breakers, historically
higher autocorrelation in trends)?

- **H0:** Time-series trend-following on BTC/ETH does not improve net-of-cost
  Sharpe over buy-and-hold of the same assets.
- **H1 (alternative):** It does, plausibly by more than on equities, because
  crypto's trend persistence and drawdown severity are both larger — bigger
  trends to capture, bigger crashes to avoid.

| Element | Specification |
|---|---|
| Universe | BTC-USD, ETH-USD (Alpaca-tradable, yfinance-covered for the backtest). A third name is added only if it has enough history to backtest meaningfully. |
| Signal | Identical rule to H2: hold only if trailing 252-day return exceeds the risk-free rate over the same window, else hold cash. |
| Sample caveat, stated now before any result exists | Free daily history via yfinance starts 2014-09-17 (BTC-USD) and 2017-11-09 (ETH-USD) — a much shorter and more survivorship/regime-narrow sample than the 2007-start equity universe. A crypto backtest here covers at most ~12 and ~9 years respectively, mostly a single secular bull-then-bust regime. Any Sharpe from this sample is **not** comparable in statistical power to H1-H7's 2007-2025 window, and must be reported with that caveat attached every time, not as a footnote once. |
| Operational note | Crypto markets trade 24/7 with no open/close. `scripts/run_live.py`'s market-hours gating (`broker.clock()`, `is_open`) does not apply to a crypto sleeve and must be handled separately before any live crypto sleeve is deployed — not assumed to just work because the equity code already exists. |

**Stated prior:** I expect this to look better in-sample than H1 or H2 on
equities, and I am specifically suspicious of that outcome in advance: a
short sample dominated by one multi-year bull run followed by sharp
drawdowns is exactly the setup where a trend rule looks artificially good by
construction. The H5 sub-period stability test (Sharpe by calendar year) is
mandatory here, not optional, before any positive result is trusted.

---

### H9 — Options protective-hedge overlay, forward-test only, no historical backtest (added 2026-09-10, post-hoc)

**Context and an upfront limitation, stated before anything is built.**
Rigorous historical options backtesting requires a paid options-chain dataset
(CBOE DataShop, OptionMetrics); no free equivalent exists back to 2007. This
hypothesis **cannot** go through the same train/validation/test sequence as
H1-H8. It is deployed directly as a forward test, exactly like H1's live
deployment, except H1 at least had a historical backtest behind its live run
and this does not. Every report of this hypothesis's results must say so.

**Research question.** Does a protective-put (or collar) overlay, sized off
the live book's own notional exposure, reduce realised drawdown by materially
more than its cost in premium (negative carry) over the forward-test window?
This is functionally a more precise, priced alternative to the blunt
exposure-halving circuit breaker already in `src/risk.py` (see
`docs/risk_management.md`), which reduces exposure in fixed steps rather than
buying a specific, known floor.

- **H0:** The realised cost of the hedge (premium paid, net of any collar
  premium received) exceeds the drawdown it prevented, measured against the
  unhedged book over the same window.
- **H1 (alternative):** The hedge earns its cost — drawdown reduction exceeds
  premium spent, or the hedge is disclosed as a deliberately-accepted
  insurance cost even when it doesn't (insurance that isn't used is not a
  failed hedge; that framing must be stated explicitly in any writeup, not
  retrofitted after seeing whether a crash happened to occur).

| Element | Specification |
|---|---|
| Instrument | Exchange-listed US equity index/ETF options via Alpaca's options paper API, priced off Alpaca's live options chain. Underlying: SPY, matched to the book's largest single correlated exposure. |
| Structure | Protective put initially (simplest, easiest to reason about cost); a collar (short call funding the put) considered as a sensitivity once the plain put's carry cost is measured, not assumed upfront. |
| Sizing | Notional and strike chosen to target a specific floor (e.g. no more than X% loss on the hedged notional), not chosen after seeing a drawdown, and logged with the reasoning at the time of each roll. |
| Rebalance / roll | Monthly, matching H1's rebalance cadence, to keep operational complexity bounded. |
| Disclosed limitations | (1) No historical backtest, as stated above. (2) Alpaca paper options pricing may not perfectly reflect real bid-ask spreads or fill quality on illiquid strikes/expiries — any measured "cost" is a paper-market approximation, same caveat class as H6's short-mechanics disclosure. (3) A forward test through a period with no large drawdown will show the hedge as pure cost with no offsetting benefit — that is not evidence the hedge doesn't work, only that it wasn't tested by the sample period, and must be reported that way. |

**Decision rule for deployment.** Requires: (a) `src/broker.py` extended to
place options orders (not built yet), (b) a documented cost/carry measurement
method agreed before the first hedge is placed, (c) explicit sign-off that
this sleeve's results will be read as a forward test with no backtest prior,
never presented as validated the way H1-H6 are.

---

### Amendment to H9 — external prior located after deployment (2026-09-10, same day)

**This amends the *expectation*, not the specification.** H9's spec above is
unchanged and the live position stays open. What changed is that a strong
external prior was found *after* the hedge was placed but *before* any live
result exists, and pre-registration discipline requires recording it now
rather than after the outcome is known.

H9's pre-registration stated that no historical backtest was possible because
free options data does not exist. That remains true of *our* ability to test
it. It was incomplete as a claim about available *evidence*: AQR ran this
backtest with paid OptionMetrics data and published the result.

**AQR (Ilmanen, Thapar, Tummala & Villalon, *Tail Risk Hedging: Contrasting
Put and Trend Strategies*, July 2020)** tested buying a **5% OTM one-month
S&P 500 index put, rolled at expiry**, over **1985-2020**. H9 as deployed buys
a ~5% OTM SPY put at 21-35 DTE, rolled inside 14 DTE. These are effectively
the same strategy.

Their result, scaled to 10% volatility: geometric mean **−6.4%**, Sharpe
**−0.61**, max drawdown **−92%**, equity correlation −0.64 — and those Put
figures are **gross of trading costs and fees**, while their comparison
trend-following strategy (+8.7%, Sharpe +0.84) is reported net of costs.

**Revised prior, recorded before H9's live result exists:** the expected
outcome of H9 over any period without a severe equity drawdown is a
**persistent premium bleed**, and the expected long-run return of this
specification is **negative**. If the live forward test shows exactly that,
it is the *predicted* result and must not be reported as a surprise, a bug, or
a reason to retune the spec. If it shows something else over a four-month
window, that is far more likely to be a small sample than a refutation of 35
years of evidence.

**Insurance that is never claimed on is not a failed hedge** — that framing
was already committed in H9's original text and is reaffirmed here, so it
cannot look like a rationalisation invented after seeing a loss.

See `research/institutional_landscape.md` §6 for the full evidence and the
proposed follow-up comparison (H10: put versus trend as drawdown mitigation).

