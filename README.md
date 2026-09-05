# Systematic Equity Trading Research & Live Paper Portfolio

> ⚠️ **This project uses simulated paper trading only. No real money is
> deposited, committed, or at risk. Nothing here is investment advice, and no
> result should be read as evidence of real-world trading performance.**

An end-to-end quantitative research project: from hypothesis, through
backtesting under realistic transaction costs, to a strictly untouched
out-of-sample test, and finally live execution in a simulated broker account.

**Status:** Week 1 of 12 — foundations complete, strategy research not yet begun.
Results sections below are marked `[pending]` until the code that produces them
has been run. Nothing is reported here that has not been computed.

---

## The research question

> Do cross-sectional and time-series trend signals on a fixed universe of
> liquid US ETFs deliver risk-adjusted returns that survive realistic
> transaction costs, parameter perturbation, and a strictly untouched
> out-of-sample period?

And the secondary question, which is the more interesting one:

> Does risk-based portfolio construction improve realised risk-adjusted
> performance *more reliably* than improvements to the signal itself?

---

## What this project is trying to demonstrate

Not a return number. Over a ten-week live window, a return number is noise, and
the final report says so explicitly.

What it aims to show is the discipline around the number: pre-registered
hypotheses, a one-touch out-of-sample rule, mechanically-tested bias controls,
honest cost modelling, and a documented record of what failed.

---

## Method at a glance

| Stage | Approach |
|---|---|
| **Universe** | 16 liquid US ETFs, fixed *ex ante*, spanning broad equity, sectors, real assets, and bonds |
| **Data** | Yahoo Finance daily adjusted closes (2007-01-03 →), FRED `DTB3` risk-free, Ken French factors |
| **Splits** | Train 2007–2016 · Validation 2017–2020 · **Test 2021–2025, touched once** · Live paper 2026 |
| **Strategies** | Cross-sectional momentum · time-series trend · short-horizon mean reversion · risk-based construction |
| **Costs** | Swept at 0/5/10/20 bps per unit turnover; **10 bps is the headline case**, 0 bps is diagnostic only |
| **Validation** | Newey–West t-stats, stationary-bootstrap Sharpe CIs, full parameter-grid stability |
| **Execution** | Alpaca **paper** API — `https://paper-api.alpaca.markets`, enforced in code |

### Bias controls

- **Look-ahead:** features are shifted one full bar before any weight is
  derived; trades execute at the *next* bar. A shift-invariance test asserts
  that perturbing prices after date *t* cannot change any weight up to *t*.
- **Survivorship:** a fixed ETF universe, plus an explicit statement that this
  reduces but does **not** eliminate the bias — these ETFs were selected knowing
  they survived.
- **Data snooping:** every hypothesis pre-registered in
  `research/hypotheses.md`; every parameter configuration evaluated is counted
  and the count reported alongside any best-in-sample result.

---

## Results

### Backtest results

`[pending — weeks 4–8]`

### Live paper trading results

`[pending — weeks 10+]`

Backtest and live results are reported in **separate sections** and are never
combined into a single track record.

### Data quality (verified 2026-09-05)

The one set of numbers available so far:

| Check | Result |
|---|---|
| Panel | 4,950 dates × 16 tickers, 2007-01-03 → 2026-09-04 |
| Structural errors | 0 |
| Calendar gaps > 5 days | 0 |
| Interior missing values | 0 |
| Adjustment consistency | 79,184 observations compared; 105 (0.13%) differ by > 1e-4; worst 15 bps |

That last check found a real bug on its first run — in the analysis code, not
the data. See `data/DATA_SOURCES.md` §4.

---

## Repository layout

```
PROJECT_PLAN.md         Full plan: stack reasoning, splits, selection rubric, timeline
REPRODUCIBILITY.md      How to re-run everything
docs/
  platforms.md          Alpaca / QuantConnect / TradingView / Backtrader evaluation
  methodology.md        Backtest mechanics                          [pending]
  risk_management.md    Risk engine design                          [pending]
  limitations.md        What this project cannot claim              [pending]
research/
  cmu_fit.md            What CMU MSCF actually says, with claims separated A/B/C
  hypotheses.md         Pre-registered hypotheses (committed before any results)
  overfitting.md        Multiple-testing accounting                 [pending]
  transaction_cost_model.md                                         [pending]
  daily_log.md          Dated research log
src/
  config.py             Configuration + paper-trading safety interlock
  data.py               Download, cache, validate, cross-check
  features.py signals.py portfolio.py risk.py backtest.py metrics.py execution.py  [pending]
tests/                  Bias and safety tests
portfolio/              Trade journal and daily snapshots            [pending]
reports/                Monthly research notes and the final paper   [pending]
admissions/             One-page summary, resume bullets, interview bank [pending]
```

---

## Reproducing this

```bash
git clone <repo-url>
cd quantitative-trading-research

python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m pytest                    # 40 tests, no network required
PYTHONPATH=. python scripts/fetch_data.py    # downloads and validates the panel
```

For live paper trading only (weeks 9+):

```bash
cp .env.example .env    # then add Alpaca **paper** keys
```

`.env` is gitignored. Credentials are never logged or printed — `BrokerConfig`
redacts them in `repr`, and a test asserts it.

See `REPRODUCIBILITY.md` for full detail.

---

## Safety

The paper-trading interlock is enforced in code, not by convention:

- `PAPER_TRADING_ONLY = True` is a module-level constant with no override.
- The endpoint check is **allow-list based** — only
  `https://paper-api.alpaca.markets` is permitted. Alpaca's live endpoint raises
  `LiveTradingBlockedError`; so does any unrecognised URL, including look-alike
  domains and typos. Unrecognised endpoints fail closed by design.
- The interlock runs *before* credentials are read, so a misconfigured
  environment never loads a secret into memory.

`tests/test_config_safety.py` covers all of the above.

---

## Honesty and ethics

- Every number is produced by committed code or quoted from a cited source with
  an access date.
- Backtest results are never presented as live results.
- Failed strategies stay in the repository with their diagnosis.
- No claim is made, anywhere, about admissions outcomes.

This project develops and practices trading strategies in a paper account — an
activity [CMU MSCF's admissions FAQ](https://www.cmu.edu/mscf/admissions/faq)
recommends prospective applicants undertake — and documents the surrounding
quantitative research. See `research/cmu_fit.md`, which separates what CMU
actually states from what is inference.

---

## License

MIT — see `LICENSE`.
