# PROJECT_PLAN.md

**Project:** Systematic Equity Trading Research & Live Paper Portfolio
**Author:** Harshit Kumar
**Started:** 2026-09-05
**Target completion:** ~2026-11-27 (12 weeks)
**Status:** Week 1 — foundations

> **This project uses simulated paper trading only. No real money is deposited,
> committed, or at risk at any point. Nothing here is investment advice.**

---

## 1. What this project is

A miniature quantitative-research project that runs the full arc a systematic
strategy actually has to survive:

```
Research question -> Hypothesis (pre-registered) -> Data -> Features -> Backtest
  -> Transaction costs -> Robustness -> Out-of-sample test -> Portfolio construction
  -> Risk engine -> Live paper execution -> Failure analysis -> Conclusions
```

The deliverable is **the reasoning and the evidence trail**, not a return number.
A reader should be able to clone this repo, re-run it, and reach the same
conclusions — including the negative ones.

### What "success" means here

Success is a repo that a quant researcher can read and say *"this person
understands what they're doing."* Concretely:

- Every performance number traces to code that a reader can re-run.
- Backtest results and live paper results are never mixed.
- At least one strategy that looked good in-sample is shown degrading, with a
  diagnosis of *why*.
- Look-ahead and survivorship bias are handled in code, with tests, not just
  asserted in prose.

Success is **not** a high paper-trading return. A high return over a 6–10 week
live window is statistically meaningless at this sample size, and the report
will say so explicitly.

---

## 2. Research question

> **Primary:** Do cross-sectional and time-series trend signals on a fixed
> universe of liquid US ETFs deliver risk-adjusted returns that survive
> realistic transaction costs, parameter perturbation, and a strictly
> untouched out-of-sample period?

> **Secondary:** Does risk-based portfolio construction (volatility targeting /
> risk parity) improve realised risk-adjusted performance more reliably than
> improvements to the signal itself?

The secondary question is the more interesting one and is under-explored in
retail-level projects. The prior going in — stated now, before results — is
that **portfolio construction will contribute more robustly than signal
tuning**, because signal parameters are the part most vulnerable to
overfitting. This prior may be wrong; that is the point of testing it.

---

## 3. Stack decisions and why

Every choice below is free. Where the brief allowed a fork, the decision and
its justification are recorded here so it can be defended in an interview.

| Layer | Choice | Why this and not the alternative |
|---|---|---|
| Language | Python 3.12 | Already installed; 3.13 also present but several scientific wheels lag a major release. Pinning 3.12 avoids a class of environment problems that waste research time. |
| Research data | `yfinance` (primary) + Stooq (independent cross-check) | Free, no key, adjusted OHLCV. Stooq is used to *cross-validate* yfinance rather than as a fallback — silent vendor disagreement is a real failure mode and checking it is cheap. |
| Risk-free rate | FRED `DTB3` (3-month T-bill) | The Sharpe denominator convention has to be stated, not assumed. FRED is authoritative and free. |
| Factor benchmarks | Kenneth French Data Library | Free, canonical, lets us regress strategy returns on Mkt-RF/SMB/HML/MOM to check whether we have alpha or repackaged beta. |
| Backtester | **Purpose-built vectorised engine** in `src/` | See §3.1 — this is the most contestable decision in the project. |
| Independent check | QuantConnect (free tier) | Re-implements the final strategy on a different engine with a different data vendor. Agreement is evidence the result is not an artefact of my own code. |
| Execution | Alpaca **paper** API | Free, global paper-only accounts, $100k default simulated balance, separate paper credentials and endpoint. |
| Dashboard | Streamlit | Already installed; a local read-only view over the logged portfolio state. |
| Tests | pytest | Bias tests are the point (§6), not decoration. |

### 3.1 Why a custom backtester instead of Backtrader

This is the decision most likely to be challenged, so the argument is recorded
in full.

**The strategy class is daily-frequency, cross-sectional, and portfolio-level.**
Its natural expression is: at each rebalance date, compute a target weight
vector from data available strictly up to that date, then trade the difference.
That is a matrix operation. Backtrader is an *event-driven, order-level*
framework — excellent for intraday logic, path-dependent orders, and stop
handling, and mismatched to a daily weight-vector strategy, where it adds a
large amount of machinery between the hypothesis and the number.

**The honest counter-argument:** rolling your own backtester is exactly where
look-ahead bugs hide, and "I wrote it myself" is not evidence it is correct.

**How this project answers that counter-argument** — three independent controls:

1. **Bias tests in `tests/`.** A shift-invariance test (perturbing prices at
   time *t+1* must not change any weight at time *t*) mechanically detects
   look-ahead. This is a stronger guarantee than a framework's reputation.
2. **QuantConnect re-implementation.** A second engine, different data vendor,
   different author's execution model. Material disagreement is a finding to
   investigate, not to hide.
3. **Deliberately simple, auditable engine.** A few hundred lines a reviewer can
   read in full, rather than trusting a black box.

Backtrader remains in scope as a *third* cross-check if time permits, but is
not on the critical path. **Trade-off accepted:** more of my own code to defend,
in exchange for a pipeline whose every step is inspectable.

---

## 4. Universe

Fixed, declared **before** any backtest, and not revised on the basis of results:

```
Broad equity   SPY  QQQ  IWM  DIA
US sectors     XLK  XLF  XLE  XLV  XLI  XLP  XLY  XLU
Real assets    VNQ  GLD  SLV
Bonds          TLT
```

**Inclusion rule (ex ante):** large, long-established, highly liquid US-listed
ETFs spanning distinct asset classes and sectors, all with price history
beginning at or before 2006-12-31, chosen for *coverage of the risk-factor
space* — not for historical performance. No ETF will be added or removed on the
basis of a backtest result. Any change to this list will be logged in
`research/daily_log.md` with a dated reason.

**The survivorship caveat, stated honestly.** These are not survivorship-bias-
free. Every ETF here exists *today*, and I selected them knowing that. ETFs that
launched and closed during the sample period are absent, and sector definitions
were reorganised mid-sample (notably the 2018 GICS change that moved large
constituents into a new Communication Services sector, altering XLK and XLY from
that date forward). The bias is far smaller than picking today's S&P 500
constituents and backtesting them to 2007 — these are index-tracking vehicles,
not firms that can go bankrupt — but it is **not zero**, and no claim in this
project will describe the universe as survivorship-bias free. See
`docs/limitations.md`.

---

## 5. Data splits

Chronological, never shuffled. Dates fixed now, before any strategy is run.

| Split | Period | Rule |
|---|---|---|
| **Train** | 2007-01-01 → 2016-12-31 | Free exploration. Form hypotheses, look at everything. |
| **Validation** | 2017-01-01 → 2020-12-31 | Model selection and parameter choice. Includes the COVID shock — a genuine regime stress test. |
| **Test (OOS)** | 2021-01-01 → 2025-12-31 | **Touched once, at the end.** Includes the 2022 bear market and the rate-hike regime. |
| **Live paper** | ~2026-09 → 2026-11 | True forward test. No historical data exists for this period at design time. |

**The one-touch rule is the core discipline of this project.** The test period is
not looked at until the strategy, its parameters, its cost model, and its risk
limits are all frozen and committed to git. The freezing commit hash is recorded
in the final report, so the sequence is externally verifiable rather than merely
claimed. If the strategy fails out of sample, **that result is reported as the
finding.** It is not a reason to go back and re-select.

The live paper window is ~10 weeks. At daily frequency that is ~50 observations
— far too few to establish skill. Its value is as evidence of **execution
capability and operational discipline**, not as performance evidence. The report
will state this plainly rather than presenting a live Sharpe ratio as if it
meant something.

---

## 6. Bias controls (the part that actually matters)

**Look-ahead.** Enforced structurally, not by care alone:

- All features are computed on a price panel, then **shifted forward one full
  bar** before any weight is derived. A signal using data through the close of
  day *t* can only affect positions from day *t+1*.
- Rebalance trades execute at the **next** bar's open (or close, tested both
  ways as a sensitivity), never the same close that generated the signal.
- `tests/test_no_lookahead.py` asserts shift-invariance mechanically: modify the
  price panel strictly after date *t*, recompute, and assert every weight up to
  *t* is bit-identical. A violation fails the test suite.

**Survivorship.** Addressed by construction (fixed ETF universe) and by the
honest caveat in §4. If the project later extends to single equities, a
point-in-time constituent source is required first, or the limitation is stated
in the same breath as the result.

**Data snooping / multiple testing.** Every hypothesis is written to
`research/hypotheses.md` *before* it is tested. Every parameter configuration
evaluated is counted, and the count is reported, so that the best in-sample
Sharpe can be assessed against the number of trials that produced it.

---

## 7. Strategy families under investigation

Four families, in priority order. Each gets a pre-registered hypothesis before
any code runs.

1. **Cross-sectional momentum** — rank the universe on trailing return, hold the
   top *k*. The canonical anomaly; the interesting question is whether it
   survives costs at this universe size.
2. **Time-series trend / absolute momentum** — long each asset only when its own
   trend is positive. Different mechanism from (1): it can de-risk to cash,
   which cross-sectional ranking structurally cannot.
3. **Short-horizon mean reversion** — the natural adversary to (1) and (2), and
   included specifically so the project is not only testing one direction of the
   same idea.
4. **Risk-based portfolio construction** — volatility targeting, inverse-vol, and
   risk parity as a *layer* applied to whichever signal wins, not as a competing
   signal. This is where the secondary research question lives.

**Optional, only if the core is stable:** a gradient-boosted cross-sectional
ranker, evaluated strictly against the momentum baseline. If it does not beat
the baseline after costs, that is reported as the result. No neural networks —
the sample size does not support them, and adding one would be decoration.

---

## 8. Strategy selection criteria (fixed before results)

The final strategy is chosen by a **pre-declared scoring rubric**, not by picking
the best number after the fact:

| Criterion | Weight | Rationale |
|---|---|---|
| Validation Sharpe, net of 10bps costs | 25% | Risk-adjusted, cost-aware, on data not used to form the hypothesis. |
| Parameter stability | 25% | Sharpe must not collapse under ±50% perturbation of each parameter. A strategy that works at one setting is a fitted artefact. |
| Max drawdown & Calmar | 15% | Survivability. |
| Turnover / capacity | 15% | A signal needing 300% annual turnover is a cost problem, not an alpha. |
| Interpretability | 10% | I must be able to defend the economic mechanism in an interview. |
| Implementation simplicity | 10% | Fewer moving parts, fewer silent failure modes in live paper. |

Note that **raw return is not a criterion**. Deliberately.

---

## 9. Repository layout

```
PROJECT_PLAN.md  README.md  REPRODUCIBILITY.md  requirements.txt  .env.example
docs/       methodology.md  platforms.md  risk_management.md  limitations.md
research/   cmu_fit.md  hypotheses.md  overfitting.md  transaction_cost_model.md
            daily_log.md  notebooks/
src/        config.py  data.py  features.py  signals.py  portfolio.py
            risk.py  backtest.py  metrics.py  execution.py  broker.py  logging_utils.py
tests/      test_no_lookahead.py  test_metrics.py  test_data.py  ...
portfolio/  trades.csv  daily_snapshot.csv
reports/    monthly/  final/
admissions/ figures/  quantconnect/
```

---

## 10. Twelve-week plan

| Week | Dates (approx) | Deliverable | Done when |
|---|---|---|---|
| 1 | Sep 8–14 | Scaffold, platform + CMU research, data-source docs, pre-registered hypotheses | Docs committed *before* any strategy code |
| 2 | Sep 15–21 | Data pipeline, vendor cross-check, EDA notebook | Panel loads reproducibly; yfinance vs Stooq agreement quantified |
| 3 | Sep 22–28 | Backtest engine + look-ahead tests | Shift-invariance test passes |
| 4 | Sep 29–Oct 5 | Strategy 1: cross-sectional momentum | Train+validation results, cost curve |
| 5 | Oct 6–12 | Strategy 2: time-series trend | Same rigour |
| 6 | Oct 13–19 | Strategy 3: mean reversion | Same rigour; expected to be the weakest — that is useful |
| 7 | Oct 20–26 | Costs, slippage, turnover, robustness grids | `research/overfitting.md` written |
| 8 | Oct 27–Nov 2 | **Freeze**, then single out-of-sample run | Freeze commit hash recorded before test data is touched |
| 9 | Nov 3–9 | Portfolio construction + risk engine + Alpaca paper integration | Paper orders executing; safety checks proven |
| 10 | Nov 10–16 | Live paper trading, daily journal | Daily snapshots accumulating |
| 11 | Nov 17–23 | Live vs backtest reconciliation, failure analysis | Slippage measured against modelled cost |
| 12 | Nov 24–30 | Final report, README, admissions artefacts | Full audit checklist passed |

Live paper trading continues past week 12; the report is written on the data
available at submission and dated accordingly.

**Schedule realism.** Weeks 4–6 are the most likely to slip, because a strategy
that produces a confusing result deserves the extra days rather than a hand-wave.
If time runs short, the correct cut is **strategy 3 (mean reversion)**, not the
robustness or out-of-sample work. Cutting validation to add a third strategy
would trade the credible part of the project for the decorative part.

---

## 11. Safety constraints (non-negotiable)

- `PAPER_TRADING_ONLY = True`, enforced in `src/config.py`.
- The only permitted Alpaca endpoint is `https://paper-api.alpaca.markets`.
  Startup raises `RuntimeError` on anything else — including a live URL that
  happens to be well-formed.
- Credentials live in `.env` (gitignored) and are never logged, printed, or
  included in tracebacks.
- No real-money account is ever connected. No deposits. Ever.

---

## 12. Honesty rules

1. Backtest results and live paper results are reported in separate sections and
   are never combined into a single track record.
2. Every number in every document is produced by committed code or quoted from a
   cited source with an access date.
3. Failed strategies stay in the repo with their diagnosis.
4. No claim is made about admissions outcomes. This project demonstrates areas
   CMU's own FAQ recommends applicants strengthen — that is the whole claim. See
   `research/cmu_fit.md`.
5. Where a result is statistically weak, the report says so, in the same sentence
   as the result.
