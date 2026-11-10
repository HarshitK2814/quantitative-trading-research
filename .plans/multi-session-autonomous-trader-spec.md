# Multi-session autonomous paper trader: spec

**Date:** 2026-11-10 · **Status:** agreed in interview, ready to plan

## Goal
An autonomous bot that trades 4-5 times per day on **Alpaca paper only**, using several strategies plus a news check, and produces an honest, verifiable record for the admissions resume.

## Decisions
| Topic | Decision |
|---|---|
| Money | Paper only. No live account. Keep the existing `src/config.py` paper-only guard. |
| Resume claim | Verified record, drawdown, and rules. **No profit claim** until 3+ months of positive, real results. Follows `admissions/resume_framing.md`. |
| Autonomy | Trades without asking. Safety limits stay anyway (below), because the goal is small losses. |
| Hosting | GitHub Actions cron, 4-5 runs per US market day. Secrets: Alpaca paper keys, `GROQ_API_KEY` (free tier). |
| Decisions | Fixed tested rules choose trades. A Groq-hosted LLM (free API) reads headlines and may only **veto or shrink** a trade, never add risk. Every call and reason is logged. |
| Universe | Liquid US ETFs (SPY, QQQ, sector ETFs), large-cap US stocks, crypto (Alpaca paper). |
| Validation | Each new strategy is pre-registered (rule plus pass/fail thresholds written first), tested on data it has not seen, and only deployed if it passes. Failures are recorded, not hidden. |

## Session times (US Eastern, to confirm in plan)
Pre-open check, open+30 min, midday, pre-close, plus a crypto/after-hours check. Exact times set in config.

## Safety limits (all configurable)
- Max loss per day: 1% of equity, then stop trading that day.
- Max per position: 5% of equity. Max per sector: 20%.
- Kill-switch: halt all trading if drawdown from peak exceeds 8%; needs manual restart.
- Stop-loss on every position. No leverage, no shorting at first.
- Skip trades when data is stale, market is closed, or the news check fails.

## Reporting (for the resume)
- Daily journal commit (already exists) plus per-trade log: time, strategy, signal, news verdict, fill, P&L.
- Weekly report: return, max drawdown, Sharpe with confidence interval, comparison with buy-and-hold SPY, and per-strategy results.
- Track record exported from Alpaca account history so numbers are checkable.

## Out of scope
Real money, options/futures, claiming profit from a short record, picking winners after the fact.

## Risks to handle
- Paper fills ignore slippage and market impact (Alpaca docs). Report this limit.
- Crypto and stock rules differ (24/7 vs market hours); separate sessions.
- LLM news reads can be wrong; hence veto-only role.
- GitHub cron can drift a few minutes; strategies must not depend on exact seconds.
- Short record means results are mostly noise; say so in reports.

## Open items for planning
1. Which 3-4 starting strategies to pre-register (e.g. trend, mean reversion, news-driven).
2. Exact session times and cron schedule.
3. Groq free tier has rate limits: keep news calls few per run, cache results, and if Groq fails, skip the trade (fail safe).
