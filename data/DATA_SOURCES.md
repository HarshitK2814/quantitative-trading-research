# Data sources

**Compiled:** 2026-09-05 · **All access dates:** 2026-09-05

Every dataset used in this project is listed here with its source, URL, access
date, frequency, coverage, and limitations. A number that cannot be traced to a
row in this table does not belong in the report.

---

## 1. Primary price data — Yahoo Finance via `yfinance`

| Field | Value |
|---|---|
| Source | Yahoo Finance |
| URL | https://finance.yahoo.com/ |
| Access library | `yfinance` 0.2.65 — https://github.com/ranaroussi/yfinance |
| Access date | 2026-09-05 |
| Frequency | Daily |
| Field used | Adjusted close (`auto_adjust=True`) |
| Universe | 16 ETFs (see `PROJECT_PLAN.md` §4) |
| Coverage retrieved | 2007-01-03 → 2026-09-04 |
| Observations | 4,950 dates × 16 tickers = 79,200 cells |
| Cache | `data/raw/prices_yfinance_20070101_20260905.parquet` + `.json` manifest |
| Cost | Free |

### Verified quality checks (run 2026-09-05)

| Check | Result |
|---|---|
| Structural errors (index sorting, duplicates, non-positive prices, dtypes) | **0** |
| Calendar gaps > 5 days | **0** |
| Interior missing values (nulls after a ticker's first listing) | **0** |
| Tickers with full history from 2007-01-03 | **16 of 16** |
| Extreme daily moves flagged (|r| > 20%) | **2** — both investigated below |

All 16 ETFs have continuous data from 2007-01-03, which confirms the ex-ante
universe rule (§4: "price history beginning at or before 2006-12-31") and means
no cross-sectional strategy is forced to handle asset entry mid-sample.

### The two flagged extreme moves

**XLE, 2020-03-09, −20.14%.** Real. The COVID crash coincided with the
Saudi–Russia oil price war; energy equities fell violently. Retained.

**SLV, 2026-01-30, −28.54%.** Real, and confirmed by cross-asset evidence
rather than assumption. GLD fell −10.27% on the same date, and both had risen
sharply into it (SLV +24% over the preceding seven sessions, GLD +13%). A
single-ticker bad print does not produce a correlated move in a related asset
with a matching run-up. This is a precious-metals blow-off and reversal.
Retained.

> **Relevance to the live period.** This event sits in 2026 — *after* the
> 2021–2025 out-of-sample window, inside the live paper-trading year. It is
> therefore not part of any backtest, but it does mean the live paper period is
> being entered after an unusually violent precious-metals regime. GLD and SLV
> behaviour during live trading should be interpreted with that in mind.

### Known limitations

- **Adjustment methodology is Yahoo's and is not independently auditable.**
  Partially mitigated by the internal consistency check in §4.
- **Not survivorship-bias free.** The universe was selected knowing these ETFs
  survived. See `PROJECT_PLAN.md` §4 and `docs/limitations.md`.
- **Yahoo is a free consumer service** with no SLA or correction guarantee.
  Silent historical revisions are possible; the Parquet cache plus manifest
  makes any revision detectable between runs rather than silent.
- **Close-only.** Intraday paths, bid/ask spreads, and volumes are not used by
  the strategy, so intraday data quality does not affect results — but it also
  means the cost model cannot be calibrated from observed spreads and must be
  assumed instead. See `research/transaction_cost_model.md`.

---

## 2. Cross-check vendor — Stooq — **BLOCKED, superseded**

| Field | Value |
|---|---|
| Source | Stooq |
| URL | https://stooq.com/ (CSV endpoint `https://stooq.com/q/d/l/`) |
| Access attempted | 2026-09-05 |
| Status | **Unavailable to automated clients** |

### What happened

Stooq was the planned independent cross-check vendor. All 16 requests failed.
Diagnosis (reproducible with `curl`):

- A plain request returns **HTTP 200**, but the body is **not CSV** — it is an
  HTML page containing a JavaScript proof-of-work challenge (a SHA-256 loop
  that must find a nonce, then POST to `/__verify` before content is served).
- With a browser `User-Agent`, the same challenge page is returned explicitly:
  `"This site requires JavaScript to verify your browser."`
- Without one, the request surfaces as HTTP 404.
- `stooq.pl` returned an empty body.

### Decision

**Abandoned, not worked around.** Defeating the challenge would require
executing JavaScript to bypass an anti-automation measure the operator has
deliberately deployed. That conflicts with the project's own data policy ("do
not rely on unreliable scraped websites") and with basic good conduct toward a
free service.

The code path is **retained** in `src/data.py::_download_stooq` with a
docstring recording the failure, so a reviewer can reproduce the finding rather
than take this write-up on trust.

---

## 3. Cross-check vendor — Alpaca market data — **designated replacement**

| Field | Value |
|---|---|
| Source | Alpaca Market Data API v2 |
| URL | https://data.alpaca.markets/v2/stocks/bars |
| Docs | https://docs.alpaca.markets/docs/trading-api |
| Frequency | Daily bars, `adjustment=all` |
| Feed | **IEX** (the only feed available to free/paper accounts) |
| Status | **Run and passed, 2026-09-05.** Paper account `PA3LG4UV7Q09`. |
| Coverage retrieved | 2018-11-01 → 2026-09-04, 1,537 bars (see coverage table) |
| Cost | Free |

### Measured coverage (not assumed)

The plan required IEX history depth to be measured rather than asserted. Bars
returned per calendar year, against yfinance as the denominator (SPY):

| Year | yfinance | Alpaca IEX | Coverage |
|---|---|---|---|
| 2007–2017 | 251–253 each | 0 | **0%** |
| 2018 | 251 | 1 | 0.4% |
| 2019 | 252 | 0 | 0% |
| 2020 | 253 | 111 | 43.9% |
| 2021 | 252 | 252 | **100%** |
| 2022 | 251 | 251 | **100%** |
| 2023 | 250 | 250 | **100%** |
| 2024 | 252 | 252 | **100%** |
| 2025 | 250 | 250 | **100%** |
| 2026 (to 09-04) | 170 | 170 | **100%** |

**This is a fortunate alignment and it should be stated as luck, not design.**
Full IEX coverage begins 2021-01-01, which is exactly the start of the
out-of-sample test window. The OOS result can therefore be cross-validated
against a genuinely independent vendor. The train (2007–2016) and validation
(2017–2020) periods have no IEX coverage and cannot be cross-checked this way —
for those, the only available control is the internal adjustment-consistency
check in §4.

### Measured agreement, 2021-01-01 → 2026-09-04

Daily returns, all 16 tickers, disagreement threshold 50 bps:

| Metric | Value |
|---|---|
| Observations compared | **22,784** |
| Disagreeing days | **31 (0.1361%)** |
| Median return correlation | **0.99906** |
| Minimum return correlation | **0.99826** (XLV) |
| Largest single-day difference | **1.167%** (SPY) |

Two vendors with different feeds — Yahoo's consolidated tape versus IEX alone —
agree on daily ETF returns to better than 0.998 correlation across every name.
The residual disagreements are concentrated on a handful of days and are
consistent with different closing-print conventions between a single exchange
and the consolidated tape.

**What this licenses, and what it does not.** It supports using yfinance as the
research source without a systematic-bias concern at daily frequency. It does
**not** mean live fills will match backtest prices: this measures *closing
price* agreement, whereas execution divergence also involves spread, timing
within the day, and IEX's thinner book. Week 11's reconciliation must keep
those separate.

### Why this is a better cross-check than Stooq was

It is the **same data source the live paper account trades against**.
Disagreement between this panel and the yfinance research panel is not an
academic curiosity: it is a direct, quantified estimate of the
research-to-execution divergence that the week-11 live-vs-backtest
reconciliation must isolate before attributing anything to slippage. Stooq
could never have supplied that.

### Limitations

- **IEX-only.** IEX carries a low single-digit share of US consolidated volume,
  so its prints are sparser than the SIP feed. History coverage is shorter than
  Yahoo's and **must be verified empirically** once credentials exist — a short
  overlap is still a valid cross-check, over fewer days.
- Requires API credentials, so it is not runnable by a reviewer who has not
  created a (free) Alpaca paper account.

---

## 4. Internal adjustment-consistency check — **run and passed**

Because the external cross-check was blocked (§2) and its replacement needs
credentials (§3), a third check was added that requires **neither**: reconstruct
adjusted returns from unadjusted prices plus the reported dividend and split
history, and compare against the vendor's own adjusted series.

Implemented as `src/data.py::verify_adjustment_consistency`.

### Result (run 2026-09-05, 2007-01-01 → 2026-09-05)

| Metric | Value |
|---|---|
| Observations compared | **79,184** |
| Days differing by > 1e-4 | **105 (0.1326%)** |
| Worst single-day difference | **0.001492 (≈15 bps)** — XLE, 2020-03-23 |
| Tickers with zero mismatches | GLD, SLV, QQQ |

Residuals cluster on high-volatility dates (2020-03-23, 2020-03-20,
2008-09-19) and on lower-priced ETFs. This is consistent with **two-decimal
price rounding**: on a $28 share, a $0.01 rounding error is ~3.5 bps, and that
error is largest exactly when daily ranges are widest. No systematic
mis-adjustment was found.

### A bug this check caught — in my own code

The first version of the reconstruction multiplied by the split ratio, on the
assumption that `auto_adjust=False` returns raw prices. It does not: yfinance's
unadjusted `Close` is **already back-adjusted for splits**, and only withholds
the dividend adjustment. The double-count produced spurious return differences
of ≈100% on 2:1 split dates (XLK, XLY, XLE, XLU on 2025-12-05) and ≈900% on
SLV's 10:1 split (2008-07-24).

This is recorded because it is the point of running such a check. The check
found a real defect on its first execution — in the analysis code rather than
the data, which is where defects usually are. The fix is annotated in
`src/data.py` with a warning against reintroducing the split term.

### What this check does NOT establish

It verifies that the adjusted series is *internally consistent with the
corporate actions the same vendor reports*. It cannot detect an error in the
underlying raw prices, or one shared by both the prices and the actions. It is
a **partial substitute** for an independent vendor, and is described as such
wherever it is cited.

---

## 5. Risk-free rate — FRED

| Field | Value |
|---|---|
| Source | Federal Reserve Bank of St. Louis (FRED) |
| URL | https://fred.stlouisfed.org/series/DTB3 |
| Series | `DTB3` — 3-Month Treasury Bill, Secondary Market Rate, Discount Basis |
| Frequency | Daily (business days) |
| Use | Excess-return denominator for all Sharpe and Sortino calculations |
| Status | Planned for week 2 |
| Cost | Free (API key optional) |

Stated explicitly because an unstated risk-free convention makes a Sharpe ratio
unfalsifiable. `DTB3` is quoted on a **discount basis** and annualised in
percent; it must be converted to a daily simple rate before subtraction, and
the conversion is unit-tested.

---

## 6. Factor benchmarks — Kenneth French Data Library

| Field | Value |
|---|---|
| Source | Kenneth R. French Data Library, Tuck School of Business |
| URL | https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html |
| Series | Fama-French 3 factors (daily) + Momentum (daily) |
| Use | Regress strategy returns on Mkt-RF/SMB/HML/MOM to test whether apparent alpha is repackaged factor beta |
| Status | Planned for week 7 |
| Cost | Free |

This is the check that distinguishes a genuine result from a leveraged market
bet. Given a universe that is 12/16 equity, it is not optional.

---

## 7. Sources considered and not used

| Source | Reason not used |
|---|---|
| Alpha Vantage | Free tier is heavily rate-limited and daily *adjusted* series moved behind the premium tier. Yahoo covers the same need without a key. |
| Nasdaq Data Link | Most ETF price products now require a paid subscription. |
| Kaggle datasets | Redistributed snapshots of unclear provenance and vintage. A dataset without an authoritative origin cannot anchor a reproducibility claim. |
| Polygon / Tiingo / IEX Cloud paid tiers | Cost. |
| Bloomberg / Refinitiv / WRDS | Cost and no institutional access. |

---

## Reproducibility

Regenerate the price panel and all checks:

```bash
PYTHONPATH=. python scripts/fetch_data.py
```

Cached Parquet files are **not** committed (see `.gitignore`) because they are
regenerable and would bloat the repository. Each cache file is accompanied by a
JSON manifest recording vendor, requested window, tickers returned, row count,
date range, and UTC retrieval timestamp — so a reviewer can confirm what a given
result was computed from.

**Caveat on exact reproducibility:** Yahoo may revise historical data, so a
re-run at a later date can differ in the final decimal places. The manifest
makes such a change detectable. Any material difference must be reported rather
than silently absorbed.
