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

---

## 2026-09-05 — Week 1, Day 1 (evening): broker connected, cache bug found

**Done**

- Alpaca paper account connected and verified. Account `PA3LG4UV7Q09`, ACTIVE,
  $100,000.00 equity, matching the documented default.
- `scripts/verify_broker.py`: self-tests the interlock against six unsafe
  configurations before loading any credential, then calls `/v2/account` and
  prints a redacted summary. All six blocked, paper endpoint allowed.
- Ran the Alpaca cross-check that was previously blocked on credentials.

**Findings**

7. **Cache-poisoning bug in my own code.** `_cache_path` keyed only on
   (vendor, start, end), ignoring the ticker set — and `use_cache=False`
   skipped reading but still *wrote*. So `verify_adjustment_consistency`'s
   per-ticker downloads silently overwrote the 16-ticker panel with a
   single-column TLT panel, and every later run read that back believing it was
   the full universe. **No error was raised at any point.**

   This is the worst class of research bug: it does not fail, it just makes
   results quietly wrong and irreproducible. Fixed by including a SHA-1
   fingerprint of the sorted ticker set in the cache filename, plus four
   regression tests. Found only because a `KeyError` happened to surface it —
   which is luck, not process. Worth remembering that the manifest would have
   caught it too, had I read it.

8. **Alpaca IEX coverage measured, not assumed.** Zero bars before 2018;
   43.9% of 2020; **100% from 2021-01-01 onward.** Full coverage begins exactly
   at the out-of-sample test boundary. This is luck and will be reported as
   luck — but it means the OOS result can be cross-validated against an
   independent vendor. Train and validation periods cannot be.

9. **Vendor agreement is strong.** yfinance vs Alpaca IEX daily returns,
   2021-01-01 → 2026-09-04: 22,784 observations, 31 disagreements (0.136%),
   median return correlation 0.99906, minimum 0.99826, largest single-day
   difference 1.17%. Supports using yfinance as the research source at daily
   frequency. Does **not** speak to execution divergence — that involves
   spread, intraday timing, and IEX book depth, and stays a week-11 question.

10. **Paper account offers 4x buying power** ($400k against $100k cash). The
    project is long-only and unlevered, so sizing is against cash. The
    verification script reports the discrepancy explicitly so a future bug
    cannot quietly spend margin.

**Decisions**

- **Declined the Alpaca MCP server.** It would put a second copy of the
  credentials in a global Claude config, and — more importantly — it bypasses
  `src/config.py`'s paper-only interlock entirely. The deliverable is committed,
  auditable code a reviewer can read; an MCP server contributes nothing to the
  repository. Convenience for the agent, zero value for the artefact.

**Next**

- FRED `DTB3` loader with unit-tested discount-basis → daily-simple conversion.
- Feature layer with the one-bar shift and the shift-invariance test.
