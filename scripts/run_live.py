"""Daily live PAPER trading run.

    PYTHONPATH=. python scripts/run_live.py              # dry run (default)
    PYTHONPATH=. python scripts/run_live.py --execute    # submit paper orders
    PYTHONPATH=. python scripts/run_live.py --snapshot   # record state only

**Dry run is the default.** Orders are only submitted when ``--execute`` is
passed explicitly, so an accidental invocation cannot trade.

Deployed sleeves
----------------
Live capital is allocated across the ``SLEEVES`` registry below (see
``src/sleeves.py``), each a pre-registered strategy from
``research/hypotheses.md`` running against a fixed fraction of account
equity. Today that registry holds exactly one sleeve:
``H1-momentum-126-21-k5-monthly`` at 100%, committed before any backtest was
run.

That strategy was **REJECTED** on train-period evidence (see
``research/overfitting.md``): its bootstrap Sharpe CI includes zero, and only
36% of its parameter grid beat an equal-weight benchmark.

It is deployed anyway, deliberately, as a **forward test of a pre-registered
and rejected hypothesis**. The question being asked is not "will this make
money" but "does live experience agree with the backtest's rejection?" Because
the parameters were fixed in git before any result existed, nothing here is
fitted, which makes this a genuinely clean out-of-sample observation.

It must never be described as a selected or recommended strategy. The same
rule applies to every future sleeve added to the registry: a sleeve is
switched on only after its own hypothesis is pre-registered and backtested,
and switched off only by a dated, logged decision -- never as a reaction to
a run of losing days. See ``src/sleeves.py`` for why.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, date, datetime

import pandas as pd

from src.broker import AlpacaPaperBroker
from src.config import SPLITS, UNIVERSE
from src.data import load_prices
from src.execution import (
    estimate_turnover,
    load_snapshots,
    plan_orders,
    planned_orders_frame,
    record_snapshot,
    record_trade,
    update_fills,
)
from src.risk import check_and_adjust, exposure_report
from src.signals import cross_sectional_momentum
from src.sleeves import Sleeve, combined_target_weights, validate_allocation

# ---------------------------------------------------------------------------
# Live sleeve registry -- this list IS the deployment decision.
#
# Only H1 is active, at 100% of account capital, exactly as deployed on
# 2026-09-05. Adding a second sleeve here is a live-capital decision that
# needs the same bar H1 got (pre-registered in research/hypotheses.md,
# backtested, logged) -- see src/sleeves.py's module docstring. Building the
# combiner does not, by itself, change what is trading.
# ---------------------------------------------------------------------------
SLEEVES: list[Sleeve] = [
    Sleeve(
        name="H1-momentum-126-21-k5-monthly",
        hypothesis_id="H1",
        capital_fraction=1.0,
        signal_fn=lambda prices: cross_sectional_momentum(prices, rebalance="D"),
        allow_short=False,
        active=True,
        note="Deployed 2026-09-05 as a forward test of a pre-registered, "
             "rejected hypothesis. See research/overfitting.md.",
    ),
]

STRATEGY_VERSION = "+".join(s.name for s in SLEEVES if s.active)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("run_live")
pd.set_option("display.width", 200)


def build_target_weights(
    as_of: date,
) -> tuple[pd.Series, pd.Timestamp, dict[str, pd.Series]]:
    """Compute today's combined target weights across all active sleeves.

    Each sleeve's signal reblances daily so its vector always reflects the
    current top-k; the execution engine's min-notional filter suppresses
    trading when nothing has changed, which reproduces monthly turnover
    without needing to be run on exactly the right calendar day.

    Returns:
        The combined weight vector, the signal date it was formed from, and
        each active sleeve's own (unscaled) weights for attribution/logging.

    """
    validate_allocation(SLEEVES)
    prices = load_prices(UNIVERSE, SPLITS.history_start, as_of, refresh=True)
    combined, per_sleeve = combined_target_weights(SLEEVES, prices)
    return combined, prices.index[-1], per_sleeve


def main() -> None:
    """Run one daily cycle: reconcile, risk-check, trade, journal."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                        help="Submit orders. Without this flag, nothing trades.")
    parser.add_argument("--snapshot", action="store_true",
                        help="Record portfolio state only; generate no orders.")
    args = parser.parse_args()

    broker = AlpacaPaperBroker()
    account = broker.get_account()
    clock = broker.clock()

    print("=" * 96)
    print(f"LIVE PAPER RUN | {datetime.now(UTC).isoformat(timespec='seconds')}")
    print(f"Strategy: {STRATEGY_VERSION}")
    print("*** PAPER TRADING - SIMULATED MONEY ONLY - NO REAL CAPITAL ***")
    print("=" * 96)
    print(f"Account {account.account_number} | status {account.status} | "
          f"equity ${account.equity:,.2f} | cash ${account.cash:,.2f}")
    print(f"Market open: {clock['is_open']} | next open {clock['next_open']}")

    if account.trading_blocked:
        raise SystemExit("Account trading is blocked; aborting.")

    positions = broker.get_positions()
    print(f"Open positions: {len(positions)}")

    refreshed = update_fills(broker)
    if refreshed:
        print(f"Journal: wrote {refreshed} fill-update rows.")

    # -- portfolio state ---------------------------------------------------
    position_values = pd.Series(
        {s: p.market_value for s, p in positions.items()}, dtype=float
    )
    exposure = exposure_report(position_values, account.equity)

    history = load_snapshots()
    equity_history = (
        pd.concat([history["equity"], pd.Series([account.equity])], ignore_index=True)
        if not history.empty
        else pd.Series([account.equity])
    )
    starting_equity = (
        float(history["equity"].iloc[0]) if not history.empty else account.equity
    )
    peak = float(equity_history.max())

    daily_return = (
        account.equity / account.last_equity - 1.0 if account.last_equity else 0.0
    )
    cumulative_return = account.equity / starting_equity - 1.0
    drawdown = account.equity / peak - 1.0

    print(f"Daily return {daily_return:+.4%} | cumulative {cumulative_return:+.4%} "
          f"| drawdown {drawdown:.4%}")
    print(f"Gross exposure {exposure['gross_exposure']:.4f} | "
          f"cash weight {exposure['cash_weight']:.4f}")

    # -- signal + risk -----------------------------------------------------
    orders_submitted = 0
    turnover = 0.0

    if not args.snapshot:
        raw_weights, signal_date, per_sleeve = build_target_weights(date.today())
        print(f"\nSignal formed from data through {signal_date.date()} "
              f"(one-bar lag already applied).")
        for sleeve_name, weights in per_sleeve.items():
            held = weights[weights.abs() > 1e-9].sort_values(ascending=False)
            print(f"  Sleeve {sleeve_name!r} (own weights, unscaled): "
                  f"{held.round(4).to_dict()}")

        report = check_and_adjust(
            raw_weights, equity_history=equity_history, positions=positions
        )
        print(report.summary())

        selected = report.adjusted[report.adjusted > 0].sort_values(ascending=False)
        print("\nTarget portfolio:")
        for symbol, weight in selected.items():
            print(f"  {symbol:<5} {weight:>7.4f}")

        prices_now = broker.get_last_prices(list(UNIVERSE))
        if len(prices_now) < len(UNIVERSE):
            missing = sorted(set(UNIVERSE) - set(prices_now))
            print(f"  NOTE: no IEX print for {missing}; "
                  f"falling back to position marks where held.")

        planned = plan_orders(
            report.adjusted, positions, account.equity, prices_now
        )
        turnover = estimate_turnover(planned, account.equity)

        print(f"\nPlanned orders: {len(planned)} | "
              f"estimated turnover {turnover:.4f}")
        if planned:
            print(planned_orders_frame(planned)[
                ["symbol", "side", "qty", "reference_price", "notional",
                 "current_weight", "target_weight"]
            ].to_string(index=False))

        if args.execute:
            print("\n--- SUBMITTING PAPER ORDERS ---")
            stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
            for order in planned:
                try:
                    result = broker.submit_order(
                        symbol=order.symbol,
                        qty=order.qty,
                        side=order.side,
                        order_type="market",
                        time_in_force="day",
                        client_order_id=f"{STRATEGY_VERSION[:20]}-{order.symbol}-{stamp}",
                    )
                    record_trade(order, result, STRATEGY_VERSION, account.equity)
                    orders_submitted += 1
                    print(f"  {order.side:<4} {order.qty:>4} {order.symbol:<5} "
                          f"-> {result.status} ({result.order_id[:8]})")
                except Exception as exc:  # noqa: BLE001 - log and continue
                    logger.error("Order failed for %s: %s", order.symbol, exc)
                    print(f"  FAILED {order.symbol}: {exc}")
        else:
            for order in planned:
                record_trade(order, None, STRATEGY_VERSION, account.equity,
                             dry_run=True)
            if planned:
                print("\nDRY RUN - nothing submitted. Re-run with --execute to trade.")

    # -- snapshot ----------------------------------------------------------
    spy_price = broker.get_last_prices(["SPY"]).get("SPY")
    record_snapshot(
        {
            "date": date.today().isoformat(),
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "strategy_version": STRATEGY_VERSION,
            "equity": round(account.equity, 2),
            "last_equity": round(account.last_equity, 2),
            "cash": round(account.cash, 2),
            "daily_return": round(daily_return, 8),
            "cumulative_return": round(cumulative_return, 8),
            "drawdown": round(drawdown, 8),
            "gross_exposure": round(exposure["gross_exposure"], 6),
            "net_exposure": round(exposure["net_exposure"], 6),
            "cash_weight": round(exposure["cash_weight"], 6),
            "n_positions": exposure.get("n_positions", 0),
            "max_position_weight": round(exposure.get("max_position_weight", 0.0), 6),
            "positions_json": json.dumps(
                {s: round(p.qty, 4) for s, p in sorted(positions.items())}
            ),
            "benchmark_spy": spy_price,
            "notes": f"orders_submitted={orders_submitted};turnover={turnover:.4f}",
        }
    )
    print("\nSnapshot recorded -> portfolio/daily_snapshot.csv")
    print("PAPER TRADING ONLY. No real money involved.")


if __name__ == "__main__":
    main()
