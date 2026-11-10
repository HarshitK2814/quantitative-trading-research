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
