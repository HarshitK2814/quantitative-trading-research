# Strategy Search & Ensemble — Spec (2026-11-21)

## Goal
Find strategies that **beat SPY risk-adjusted** on the Alpaca **paper** account, by searching many strategy families with strict overfitting controls, then running survivors as a risk-parity ensemble.

## Decisions
| Topic | Decision |
|---|---|
| Record | New labelled **exploratory "search" track**. Pre-registered record (H1, S1–S3, O1–O2, test window) left as written. Every trial logged. |
| Risk | Max drawdown **-15%**, **no leverage**: gross exposure ≤ 100%. |
| Kill switch | Account **-10% from peak → halve** exposure; **-15% → flat**. Resume only after manual review. |
| Instruments | ETFs, stocks (long and short), options (spreads, puts, covered calls), leveraged/inverse ETFs, crypto. |
| Leveraged ETFs | Exposure counts as notional × leverage (e.g. SQQQ $10k = $30k). |
| Success metric | Higher Sharpe and smaller max drawdown than SPY. Raw return is secondary. |
| Combine | **Risk-parity ensemble** (inverse-vol), per-sleeve cap. |
| Existing sleeves | H1, S1, S2, O1, O2 **compete** as candidates; retire if they fail. Live log kept. H1 stays paused until it passes. |
| Frequency | Daily bars, plus 30-min bars at the **4 existing session checkpoints** (open, mid_morning, late_morning, noon). No all-day bot. |
| Arbitrage | **Stat-arb only** (pairs/cointegration, sector-neutral reversal). No true latency arbitrage. |
| Deadline | First survivors live **before Mon 2026-11-23 open**; search continues after. |

## Universe & survivorship
- **Stocks:** full S&P 500 using **point-in-time membership** (historical add/remove dates, e.g. public fja05680/sp500 dataset). A stock is tradable on day *t* only if it was in the index on *t*.
- **Delisted names:** use price history when it exists. When it doesn't (yfinance gap), apply a **-30% delisting return** on exit (Shumway 1997 style, conservative). Report results both with and without the stocks that are missing data.
- **Middle ground:** the main ranking uses the top ~150 by point-in-time liquidity (cheap to short, low cost). Full-500 runs are a robustness check.
- **ETFs:** current 16 + sector/factor/bond/commodity/inverse/leveraged ETFs (~50).
- **Crypto:** BTC, ETH.

## Strategy families (each a parameter grid)
1. Time-series trend (SMA/EMA crosses, breakouts, Donchian, vol-scaled TSMOM; Moskowitz-Ooi-Pedersen 2012).
2. Cross-sectional momentum (stocks and ETFs, 3–12m lookbacks, skip-month; Jegadeesh-Titman 1993, Asness et al 2013).
3. Short-term reversal / mean reversion (RSI(2), IBS, 5-day reversal; Lehmann 1990).
4. Stat-arb: cointegrated pairs within sector, PCA residual reversion (Avellaneda-Lee 2010).
5. Low-volatility / quality / betting-against-beta (Frazzini-Pedersen 2014).
6. Regime switching: risk-on/off by trend, VIX, credit spread; inverse-ETF hedge sleeve.
7. Seasonality: turn-of-month, overnight-vs-intraday returns, pre-holiday.
8. Volatility premium: put-write / covered-call **proxies** (CBOE PUT/BXM-style) for options; options are forward-test only.
9. Crypto trend (S3-style variants).
10. Intraday: opening-range breakout and late-morning reversal at the checkpoints (30-min bars, Alpaca IEX since 2016; disclose thin-volume bias).

## Selection (anti-overfitting)
- Splits: **train 2008–2020**, **validation 2021–2024**, **holdout 2025-01-01 → 2026-11-20, one touch**.
- Costs: 5 bps ETFs, 10 bps stocks, short borrow 1%/yr, crypto 25 bps.
- Keep a strategy only if all of these hold:
  - **Deflated Sharpe probability > 0.95**, counting the total number of trials.
  - Validation Sharpe > SPY's validation Sharpe.
  - Positive in the holdout.
  - Survives ±20% parameter perturbation.
- Trial ledger appended to the existing ledger (`run_ledger_dsr.py`).

## Deployment
- New sleeve registry entries driven by the existing `run_session.py` sessions. Every order is market or limit, paper endpoint only (already enforced).
- Ensemble weights recomputed weekly. Per-sleeve cap 25%.
- Options sleeves stay under the existing 2%-of-equity risk cap.

## Reporting
- **Live dashboard:** extend `docs/index.html` with per-sleeve P&L vs SPY, drawdown, and trades.
- **Search report:** `research/strategy_search.md` with families tested, trial count, DSR, and what failed.
- **Weekly email:** Gmail draft each Friday with week P&L vs SPY, sleeve table, and kill-switch state.

## Known limits (state openly)
- No options history: options are judged on proxies and live results only.
- Survivorship is reduced, not removed.
- IEX minute data is thin.
- Testing many strategies raises false-positive risk; DSR reduces it but does not remove it.
- Forward results over weeks are mostly noise. No profit is guaranteed.
