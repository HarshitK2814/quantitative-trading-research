# Research log

Dated, append-only. Historical entries are never edited — corrections are added
as new entries. This file is part of the evidence trail.

---

## 2026-09-05 — Week 1, Day 1: foundations

**Done**

- Repository scaffold, git init, `.gitignore` (secrets excluded before any code
  was written).
- Verified environment: Python 3.12.6, git 2.45.2. Core scientific stack already
  present. Missing and deferred: `alpaca-py` (needed week 9), `jupyterlab`.
- Researched official sources and recorded them with access dates:
  `research/cmu_fit.md`, `docs/platforms.md`, `data/DATA_SOURCES.md`.
- **Pre-registered five hypotheses** in `research/hypotheses.md` — committed
  before any strategy code exists. This ordering is the point; the git history
  is what makes it verifiable.
- Implemented `src/config.py` (paper-trading interlock) and `src/data.py`
  (download, cache, validate, cross-check).
- 40 tests passing.

**Findings**

1. **TradingView's The Leap is not unconditionally free.** Its support page
   states entry requires "an active subscription, trial, or have previously had
   a subscription." Under the project's no-payment rule, excluded. Recorded as
   a finding rather than an omission. Separately, a one-month leaderboard is a
   noise measurement — citing a rank would endorse a metric this project's own
   report argues against.

2. **Alpaca paper-only accounts get IEX-only market data.** Acceptable for
   daily-frequency large-ETF trading, but it means live fills and backtest
   prices come from *different* sources. Week 11 reconciliation must separate
   data-source divergence from genuine slippage before attributing either.

3. **Stooq is no longer accessible to automated clients.** It now serves a
   JavaScript proof-of-work challenge instead of CSV. Not worked around —
   defeating it would mean bypassing a deliberate anti-automation measure.
   Cross-check role reassigned to the Alpaca market-data API, which is a
   *better* choice anyway: it is the same feed the live account trades against,
   so the comparison directly measures research-to-execution divergence.

4. **Data panel is clean.** 4,950 dates × 16 tickers, 2007-01-03 → 2026-09-04.
   Zero structural errors, zero calendar gaps, zero interior missing values.
   All 16 ETFs have full history from 2007-01-03, confirming the ex-ante
   universe rule holds and no asset enters mid-sample.

5. **Two extreme moves flagged, both real.** XLE −20.1% (2020-03-09, COVID +
   oil price war). SLV −28.5% (2026-01-30) — confirmed real by cross-asset
   evidence: GLD fell −10.3% the same day and both had run up sharply into it.
   A single-ticker bad print does not produce a correlated move in a related
   asset. Note this sits in the *live* year, not any backtest window.

6. **The adjustment-consistency check caught a bug in my own code.** First
   version multiplied by the split ratio, assuming `auto_adjust=False` returns
   raw prices. It does not — yfinance's unadjusted `Close` is already
   split-adjusted and withholds only dividends. The double-count produced ~100%
   spurious return differences on 2:1 split dates and ~900% on SLV's 10:1
   split. After the fix: 105 of 79,184 observations (0.13%) differ by > 1e-4,
   worst case 15 bps, residuals consistent with two-decimal price rounding.

**Decisions**

- **Custom vectorised backtester over Backtrader.** The strategy class is a
  daily weight vector, which Backtrader's event-driven architecture does not
  express naturally. Counter-argument acknowledged (own code hides look-ahead
  bugs) and answered with three controls: mechanical shift-invariance tests, a
  QuantConnect re-implementation, and a deliberately small auditable engine.
  Full argument in `PROJECT_PLAN.md` §3.1.
- **Splits fixed now:** train 2007–2016, validation 2017–2020, test 2021–2025
  (one touch), live 2026. Fixed before any strategy exists so they cannot be
  chosen to flatter a result.
- **Rejection rule pre-declared:** a strategy is rejected if fewer than 60% of
  its parameter-grid configurations beat the equal-weight benchmark net of
  10 bps — regardless of peak performance. Set now so it cannot be relaxed later.

**Open questions**

- Does IEX history via Alpaca cover enough of 2007–2026 to be a useful
  cross-check, or only recent years? Must be measured, not assumed.
- Is `pct_change` on the ETF panel the right return definition for GLD/SLV
  given the 2026 volatility regime, or should the live period use log returns
  for vol estimation? Deferred to week 2.

**Next (week 2)**

- FRED `DTB3` loader with unit-tested discount-basis → daily-simple conversion.
- EDA notebook: correlation structure, volatility regimes, autocorrelation.
- Feature layer with the one-bar shift, plus the shift-invariance test.
