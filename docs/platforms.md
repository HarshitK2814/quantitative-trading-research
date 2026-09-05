# Platform evaluation

**Compiled:** 2026-09-05 · **All sources accessed:** 2026-09-05

Every platform below is used on a free tier. **No payment is made to any
platform for this project.** Where a "free" offering turns out to have a
paywall condition, that is recorded rather than glossed over.

---

## Summary of decisions

| Platform | Role in this project | Verdict |
|---|---|---|
| **Alpaca** | Live paper execution — the primary execution venue | **Adopted** |
| **QuantConnect** | Independent re-implementation of the final strategy | **Adopted (secondary)** |
| **Backtrader** | Possible third cross-check | **Deferred** — not on critical path |
| **TradingView** | Charting; The Leap competition | **Charting only. The Leap excluded** — see §4 |

---

## 1. Alpaca — adopted as the execution venue

Sources: [alpaca.markets](https://alpaca.markets/) ·
[Paper Trading docs](https://docs.alpaca.markets/docs/paper-trading) ·
[Trading API docs](https://docs.alpaca.markets/docs/trading-api)

### Verified facts

| Property | Finding (verbatim where quoted) |
|---|---|
| Paper endpoint | `https://paper-api.alpaca.markets`; docs instruct setting `APCA_API_BASE_URL` to it |
| Default balance | "$100k balance as a default setting" |
| Cost | Paper trading is free and "available to all Alpaca users" |
| Credentials | Paper accounts use "a different API key from your live account" |
| International access | "Anyone globally can create an Alpaca **Paper Only Account**! All you need to do is sign up with your email address." |
| Account management | Users can "create and delete paper accounts, rather than resetting them" |

### Documented limitations — quoted, because they shape the research

Alpaca states that paper trading does **not** account for:

> "Market impact of your orders" · "Information leakage of your orders" ·
> "Price slippage due to latency" · "Order queue position (for non-marketable
> limit orders)"

Also excluded: dividends, order fill emails, regulatory fees; borrow fees are
listed as "Coming Soon". Orders receive "partial fills for a random size 10% of
the time."

### The constraint that actually matters

**Paper-only accounts receive exclusively IEX market data.** IEX is a single
exchange carrying a low single-digit percentage of US consolidated volume, so
its quotes are thinner and its prints sparser than the consolidated SIP feed a
live account can access.

**Why this is acceptable here [C]:** the strategy is daily-frequency and trades
only large, highly liquid ETFs. Daily closing prices from IEX for SPY-class
instruments track consolidated prices closely. Research and backtesting use
Yahoo/Stooq data anyway — IEX only affects the live paper fills.

**Why it is still recorded as a limitation:** it means live paper fill prices
and my backtest's assumed prices come from *different* data sources, so some
divergence between live and backtested results is expected for reasons that
have nothing to do with the strategy. Week 11's reconciliation must separate
data-source divergence from genuine slippage before attributing either.

### Why Alpaca over the alternatives

Free, global paper-only signup (critical — many US brokers' paper environments
are unavailable internationally), a documented REST API with an official Python
SDK, a hard endpoint separation between paper and live, and published
limitations. That last point is worth something: a vendor that documents what
its simulator gets wrong is more useful than one that does not.

### Safety posture

`src/config.py` refuses to start unless the base URL is exactly the paper
endpoint and `PAPER_TRADING_ONLY=true`. No live-money account will be created or
connected at any point in this project.

---

## 2. QuantConnect — adopted as an independent check

Sources: [quantconnect.com](https://www.quantconnect.com/) ·
[Pricing](https://www.quantconnect.com/pricing) ·
[Docs](https://www.quantconnect.com/docs/)

### Free tier, as documented

| Property | Finding |
|---|---|
| Backtesting | "Unlimited Backtesting" |
| Data | "Equity, Indexes, Forex, Crypto, Futures, Options Data"; minute/hour/daily resolution (no tick/second) |
| Fundamentals | Corporate Fundamentals **not** included on the free tier |
| Nodes | 1 research node, 1 backtest node |
| Limits | 200 projects · 500 MB workspace · 32 KB per file · 3 MB/day log reads · 10 KB per backtest log |
| Live trading | Paper trading only on the free tier |
| Local development | LEAN-CLI **not** available on the free tier |
| Support | "Community Support" |

### Role in this project [C]

QuantConnect is **not** the primary research environment — the 32 KB file limit
and absence of LEAN-CLI make it awkward for iterative local work, and its
web-IDE-only workflow does not fit a git-centred project.

Its value is specific and worth the setup cost: **re-implementing the final
frozen strategy on a second engine, with a second data vendor and a
third-party execution model.** If two independent implementations agree, the
result is unlikely to be an artefact of my own backtester. If they disagree
materially, that is a genuine finding and gets investigated in the report
rather than quietly dropped.

The absence of free Corporate Fundamentals also confirms that a
fundamentals-driven factor strategy is out of scope for a zero-budget project.

---

## 3. Backtrader — deferred

Source: [backtrader.com](https://www.backtrader.com/) ·
[docs](https://www.backtrader.com/docu/)

Open source, free, runs locally, mature and well documented.

**Why deferred [C]:** Backtrader is event-driven and order-level. This project's
strategies are daily-frequency portfolio weight vectors, which that architecture
does not express naturally. Its genuine strengths — intraday event handling,
path-dependent order logic, broker simulation — are not exercised by the
strategy class here.

Adding it would mean maintaining a third implementation to gain a cross-check
that QuantConnect already provides more independently (different data vendor,
different execution model, different author). Reconsidered only if the project
extends to intraday execution or path-dependent orders.

See `PROJECT_PLAN.md` §3.1 for the full argument, including the case against
this decision.

---

## 4. TradingView — charting only; The Leap excluded

Sources: [tradingview.com](https://www.tradingview.com/) ·
[Paper trading](https://www.tradingview.com/support/solutions/43000516466-paper-trading-main-functionality/) ·
[The Leap](https://www.tradingview.com/the-leap/) ·
[What is The Leap](https://www.tradingview.com/support/solutions/43000771594-what-is-the-leap/)

### The eligibility finding

TradingView's own support page states:

> "The Leap is open to all users with an eligible TradingView account — you can
> join if you have an active subscription, trial, or have previously had a
> subscription."

**The Leap is therefore not unconditionally free.** Entry requires a current
paid subscription, a trial, or a lapsed paid subscription. A free-tier account
that has never subscribed does not qualify on the plain reading of that
sentence.

### Decision [C]

**Excluded from the project plan.** The governing rule for this project is that
no paid access is purchased. A free trial is a technical workaround, but it
normally requires payment details and converts to a paid plan by default — that
is a paid-plan commitment with a delay, not a free option.

Recorded as a **finding**, not an oversight: it was investigated against the
official source and ruled out on documented eligibility grounds. If TradingView
later runs an edition open to never-subscribed free accounts, it can be
revisited — as a **bonus external datapoint only**, never as a load-bearing
part of the project.

### Other Leap facts, for completeness

- "Each edition of The Leap runs for a set period, usually, about a month."
- Participants receive "a fixed amount of virtual money" (amount not stated on
  the page).
- "All trading activity takes place in real time with simulated execution."
- "Performance is ranked on a public leaderboard, and results are determined at
  the end of the contest period." Ranking methodology is not detailed.

### Why not depending on it was the right call anyway [C]

A one-month leaderboard ranking is a **noise measurement**. Over ~20 trading
days, ranking among thousands of participants is dominated by variance and by
who took the largest bets, not by strategy quality — the winner of such a
contest is typically whoever was most concentrated and got lucky. Citing a good
rank would mean endorsing a metric this project's own report argues against.

TradingView remains useful for charting and manual market observation, which is
free and requires no account tier.

---

## 5. What is deliberately not used

| Excluded | Reason |
|---|---|
| Bloomberg, Refinitiv, WRDS | Cost. Not available without institutional access. |
| Polygon paid tiers, premium data vendors | Cost. Free sources are sufficient at daily frequency. |
| Premium TradingView | Cost. |
| Interactive Brokers paper | Requires a funded or approved live application in most jurisdictions; Alpaca's paper-only global signup is strictly simpler. |
| Any live-money brokerage | **Out of scope by design.** Non-negotiable. |

---

## Re-verification

Platform pricing, tiers, and eligibility change. Every claim above must be
re-checked against the live pages before the final report is published, and the
re-verification date recorded. Nothing on this page should be cited from memory.
