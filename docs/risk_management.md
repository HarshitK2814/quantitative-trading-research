# Risk management

## What a limit in this code actually is

Every risk control here constrains **target weights at the moment of
rebalancing**. None of them constrain what the market does between
rebalances. A 25% position cap does not stop a position reaching 30% through
appreciation. A drawdown halt does not stop a 20% overnight gap. This is
stated explicitly because risk systems are routinely oversold as guarantees,
and this project would rather under-claim than over-claim what its own code
can do. See the module docstring in `src/risk.py`.

## Two layers

1. **Portfolio-level circuit breakers**, applied to the whole book off the
   running equity peak: de-risk (halve exposure) and halt (zero exposure).
2. **Position-level stop-loss / take-profit**, applied to each held symbol off
   its own average entry price, independent of what the H1 signal wants to do
   with that symbol. See `apply_position_stops` in `src/risk.py`.

Layer 2 exists because layer 1 alone has a blind spot: a large loss in one
name can be offset by gains elsewhere and never trip a portfolio-level
threshold at all. Position-level stops catch that case; portfolio-level
breakers catch the case where everything is down together.

## Parameter history

| Date | Portfolio de-risk | Portfolio halt | Position stop-loss | Position take-profit | Why |
|---|---|---|---|---|---|
| 2026-09-05 (deployment) | -15% | -25% | none | none | Initial values, chosen before deployment, no live P&L existed yet. |
| 2026-09-09 (tightened) | -4% | -6% | -8% | +20% | User request, one trading day into live trading, account at -0.57% / -$553 unrealised. |

The 2026-09-09 change is dated deliberately so the record shows it followed a
losing day. That does **not** mean the new numbers were fit to that day's
move — they are round, conservative figures (4/6/8/20%), not a value picked
to make -0.57% pass or fail some line. The point of writing this table is
that a reader can check that claim rather than take it on faith.

## What tightening the thresholds actually buys, and what it costs

**Buys:** the account cannot lose more than roughly 6% from its peak before
every position is forced flat, and no single name can lose more than roughly
8% of its own value before it is forced out regardless of the signal's
opinion.

**Costs, stated plainly:**

- **This is not "no more losses."** A -0.5% day, a -2% day, even several in a
  row without ever touching a peak-to-trough draw of 6%, will all pass
  through untouched. The only way to guarantee zero red days is to hold cash,
  which was not what was asked for.
- **Whipsaw risk.** A -8% single-name stop on ETFs with double-digit annual
  volatility will fire periodically in ordinary conditions, not only in
  genuine breakdowns. Getting stopped out and then having the name recover is
  an expected cost of this kind of overlay, not a bug.
- **It changes the deployed strategy.** H1's signal itself (`src/signals.py`)
  is untouched and remains the pre-registered, rejected specification — this
  overlay sits in the execution layer, not the signal. But the forward test's
  live P&L is no longer a clean read of the H1 signal alone; it is H1 filtered
  through a risk overlay chosen after one trading day of data existed. Any
  writeup of the live results must say so.
- **A halted or de-risked book earns roughly nothing while flat**, and a
  strategy that is frequently flat cannot demonstrate much about the signal
  it was supposed to be testing. If the live halt/de-risk log shows frequent
  triggers, that itself becomes a finding worth recording, not a nuisance to
  route around.

## Sharpe expectations

A Sharpe below 1 was explicitly accepted as fine when these limits were set.
This project's own train-period benchmarks (see `research/daily_log.md`)
never reach a t-statistic of 2.0 over ten years and top out around Sharpe 0.7
for a 60/40 blend — so a live Sharpe below 1, or even negative over a short
window, is consistent with everything already measured, not a sign that
something is broken.

## A third layer: H9's options hedge overlay (added 2026-09-10)

Layers 1 and 2 above (portfolio circuit breakers, position stops) both
constrain *target weights* — a blunt lever: reduce exposure in fixed steps
once a threshold is crossed. H9 (`research/hypotheses.md`) adds a third,
different kind of tool: a **priced** floor.

**Mechanism.** A SPY protective put, struck near 5% out-of-the-money,
21–35 days to expiry (rolled inside 14 DTE), sized to the book's gross
*equity-sleeve* exposure and rounded down to whole contracts. `src/hedge.py`
fixes this rule before any hedge is placed; `scripts/run_hedge.py` executes
it, journals every event append-only to `portfolio/hedge_trades.csv`, and
polls back the real fill price the same way the equity journal does (see
finding #24 — this was built with that fix from the start, not added after
finding the same bug twice).

**What it's for.** A precise, purchased floor rather than a step-function
exposure cut — the tradeoff is a known, ongoing premium cost in exchange for
a bounded worst case on the hedged notional, instead of a reactive halving
after a threshold is already breached.

**The limitation that matters most, restated from H9's pre-registration
because it cannot be said only once:** there is no free historical
options-chain data back to 2007, so **this hypothesis has no backtest behind
it at all.** Every other strategy in this project was tested before being
trusted; H9 is trusted from day one on pre-registered *reasoning* alone. Its
live track record is the only evidence that will ever exist for it. A period
with no large drawdown will show the hedge as pure cost with no offsetting
benefit — that is not evidence the hedge doesn't work, only that the sample
didn't test it, and any report of H9's results must say so rather than let a
flat P&L read as a verdict.

**First real position, for the record (not cherry-picked — it's the first
and only one so far):** opened 2026-09-10, `SPY261002P00720000` (5.0% OTM,
22 DTE at open), 1 contract, filled at $2.71/share ($271 total premium),
covering $72,000 of $88,083 equity-sleeve exposure (81.7% — the residual is
the rounding-to-whole-contracts cost, not hidden).
