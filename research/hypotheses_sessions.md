# Session-trader hypotheses (pre-registered 2026-11-10)

Parameters are the textbook values, fixed now, never tuned. Committed before any backtest.

| ID | Rule | Universe | Capital |
|---|---|---|---|
| S1 | Long when close > SMA200 and SMA50 > SMA200, else flat | SPY, QQQ, XLK, XLF, XLE, XLV | 40% |
| S2 | Long when RSI(2) < 10 and close > SMA200; exit when RSI(2) > 70 | AAPL, MSFT, NVDA, AMZN, GOOGL | 30% |
| S3 | Long when close > SMA100 and SMA20 > SMA100, else flat | BTC/USD, ETH/USD | 30% |

Signals use completed daily bars only (one-bar lag). Cost: 5 bps per unit turnover.

## Pass/fail gate (held-out window 2021-01-01 to latest)
A strategy is switched on only if, equal-weighted across its universe:
- annualised Sharpe >= 0.5, AND
- max drawdown no worse than -25%.

Fail = stays off. Result is recorded in `research/daily_log.md` either way.
No re-tuning after seeing results.

## Options sleeve (pre-registered 2026-11-10, before any options order)

**These are forward tests. No historical gate exists:** there is no free option price history, so no backtest and no pass/fail threshold can be set in advance. Results are reported as a live paper record only, and must never be called "validated".

| ID | Rule | Underlying | Risk cap |
|---|---|---|---|
| O1 (hedge) | Protective put per `src/hedge.py`: strike nearest 95% of spot, expiry 21-35 days, sized to the equity book (S1+S2 positions), rolled when < 14 days to expiry (`needs_roll`). Contracts cut so premium <= 1% of equity. Logged as a hedge, not a profit strategy. | SPY | premium <= 1% of equity |
| O2 (put credit spread) | Bull put spread: short put strike nearest 95% of spot, long put one $5 strike lower, 30-45 days to expiry. Open only if S1 trend is long for that ETF AND the Groq news gate says `ok` (not reduce, not veto) AND credit >= 20% of width AND fewer than 2 spreads open. One multi-leg (`mleg`) limit order; never two single legs; never a naked short. Max loss = (width - credit) x 100 x contracts. Close at 50% of credit captured, OR at 7 days to expiry, OR when spread value >= 2x credit (stop). Limit orders only. | SPY, QQQ | total spread max loss <= 1% of equity |

Shared rules:
- Options risk used = cost basis of O1 long puts + max loss of open O2 spreads. If used >= 2% of equity, open nothing new. Closes are always allowed.
- Runs once a day, `late_morning` session only. No new options when the kill switch or daily-loss halt is on.
- Stale or missing quotes mean skip, never trade.
- Logged to `portfolio/session_log.csv` as strategy `O1` / `O2`.
- No re-tuning after seeing results.
