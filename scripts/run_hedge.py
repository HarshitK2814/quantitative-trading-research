"""H9 forward test: options protective-put overlay.

    PYTHONPATH=. python scripts/run_hedge.py              # dry run (default)
    PYTHONPATH=. python scripts/run_hedge.py --execute    # place/roll the hedge

**No historical backtest exists behind this strategy.** Free options-chain
data does not exist back to 2007 (CBOE DataShop / OptionMetrics are paid);
see ``research/hypotheses.md`` H9. This runs live from day one with no prior
validation, unlike H1-H6. Every report of its results must say so.

Selection rule (fixed in ``src/hedge.py`` before any hedge was placed, not
re-tuned after seeing a result): SPY put, nearest strike to 5% out-of-the-
money, nearest expiry 21-35 days out, rolled once inside 14 DTE, sized to the
book's gross *equity-sleeve* exposure (not total account equity).

**Dry run is the default.** ``--execute`` must be passed explicitly.
"""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, date, datetime

from src.broker import AlpacaPaperBroker
from src.config import ASSET_CLASS
from src.hedge import (
    expiry_window,
    needs_roll,
    parse_occ_expiry,
    plan_hedge,
    record_hedge_trade,
    update_hedge_fills,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("run_hedge")

UNDERLYING = "SPY"
EQUITY_ASSET_CLASSES = ("equity_broad", "equity_sector")


def _gross_equity_exposure(broker: AlpacaPaperBroker) -> float:
    """Dollar value of the book's equity-sleeve positions.

    Deliberately excludes cash, bonds, real estate, and commodities -- the
    hedge protects the correlated-to-SPY slice of the book, not the whole
    account.
    """
    positions = broker.get_positions()
    return sum(
        p.market_value for sym, p in positions.items()
        if ASSET_CLASS.get(sym, "unknown") in EQUITY_ASSET_CLASSES
    )


def _current_hedge(broker: AlpacaPaperBroker):
    """Return the held SPY put position, if any.

    Assumes at most one hedge position is held at a time -- true as long as
    this script is the only thing opening options positions in the account.
    """
    for symbol, position in broker.get_option_positions().items():
        if symbol.startswith(UNDERLYING) and "P" in symbol[len(UNDERLYING):]:
            return position
    return None


def main() -> None:
    """Run one hedge cycle: check the existing hedge, open or roll if needed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                        help="Submit orders. Without this flag, nothing trades.")
    args = parser.parse_args()

    broker = AlpacaPaperBroker()
    account = broker.get_account()
    clock = broker.clock()
    today = date.today()

    print("=" * 96)
    print(f"H9 HEDGE RUN | {datetime.now(UTC).isoformat(timespec='seconds')}")
    print("*** PAPER TRADING - NO HISTORICAL BACKTEST - FORWARD TEST ONLY ***")
    print("=" * 96)
    print(f"Account equity ${account.equity:,.2f} | "
          f"options level {account.options_approved_level} | "
          f"options buying power ${account.options_buying_power:,.2f}")
    print(f"Market open: {clock['is_open']}")

    refreshed = update_hedge_fills(broker)
    if refreshed:
        print(f"Journal: wrote {refreshed} fill-update rows.")

    gross_exposure = _gross_equity_exposure(broker)
    print(f"Equity-sleeve gross exposure to hedge: ${gross_exposure:,.2f}")

    held = _current_hedge(broker)
    if held is not None:
        expiry = parse_occ_expiry(held.symbol)
        dte = (expiry - today).days
        print(f"Currently holding: {held.symbol} x{held.qty:.0f} "
              f"(expires {expiry}, {dte} DTE, "
              f"unrealised P/L ${held.unrealised_pl:,.2f})")
        if not needs_roll(expiry, today):
            print("Within target DTE window; no action needed.")
            return
        print(f"Inside the {14}-day roll trigger; rolling to a new contract.")
    else:
        print("No hedge currently held.")

    if gross_exposure <= 0:
        print("No equity-sleeve exposure to hedge; nothing to do.")
        return

    min_exp, max_exp = expiry_window(today)
    contracts = broker.get_option_contracts(UNDERLYING, "put", min_exp, max_exp)
    underlying_price = broker.get_last_prices([UNDERLYING]).get(UNDERLYING)
    if not underlying_price:
        print("No underlying price available; aborting.")
        return

    candidate_symbols = [c.symbol for c in contracts][:50]  # bound request size
    quotes = broker.get_option_quotes(candidate_symbols)
    selection = plan_hedge(contracts, quotes, underlying_price, gross_exposure)

    if selection is None:
        print("No suitable contract found, or exposure too small to hedge "
              "even one contract; nothing to do.")
        return

    c = selection.contract
    otm_pct = 1.0 - c.strike_price / underlying_price
    coverage_pct = selection.notional_covered / gross_exposure

    print(f"\nSelected: {c.symbol} | strike ${c.strike_price:.2f} "
          f"({otm_pct:.1%} OTM) | expires {c.expiration_date}")
    print(f"Contracts: {selection.contracts_to_buy} | notional covered "
          f"${selection.notional_covered:,.2f} of ${gross_exposure:,.2f} "
          f"({coverage_pct:.1%})")
    print(f"Estimated premium: ${selection.estimated_premium_per_contract:,.2f}"
          f"/contract | total ${selection.estimated_total_cost:,.2f}")

    base_row = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "trade_date": today.isoformat(),
        "contract_symbol": c.symbol,
        "underlying_symbol": c.underlying_symbol,
        "option_type": c.option_type,
        "strike_price": c.strike_price,
        "expiration_date": c.expiration_date.isoformat(),
        "reference_mid_price": round(
            selection.estimated_premium_per_contract / 100.0, 4
        ),
        "notional_covered": round(selection.notional_covered, 2),
        "gross_equity_exposure": round(gross_exposure, 2),
        "estimated_cost": round(selection.estimated_total_cost, 2),
        "underlying_price_at_trade": round(underlying_price, 4),
    }

    if not args.execute:
        print("\nDRY RUN - nothing submitted. Re-run with --execute to trade.")
        record_hedge_trade({
            **base_row, "action": "plan", "qty": selection.contracts_to_buy,
            "side": "buy", "position_intent": "buy_to_open",
            "filled_avg_price": None, "order_id": "", "status": "DRY_RUN",
            "dry_run": True, "note": "",
        })
        return

    print("\n--- SUBMITTING PAPER OPTION ORDERS ---")

    if held is not None:
        close_qty = int(abs(held.qty))
        close_result = broker.submit_option_order(
            symbol=held.symbol, qty=close_qty, side="sell",
            position_intent="sell_to_close", order_type="market",
        )
        record_hedge_trade({
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "trade_date": today.isoformat(), "action": "roll_close",
            "contract_symbol": held.symbol, "underlying_symbol": UNDERLYING,
            "option_type": "put", "strike_price": None,
            "expiration_date": parse_occ_expiry(held.symbol).isoformat(),
            "qty": close_qty, "side": "sell",
            "position_intent": "sell_to_close",
            "reference_mid_price": None,
            "filled_avg_price": close_result.filled_avg_price,
            "notional_covered": None, "gross_equity_exposure": gross_exposure,
            "estimated_cost": None,
            "underlying_price_at_trade": underlying_price,
            "order_id": close_result.order_id, "status": close_result.status,
            "dry_run": False, "note": "closed to roll into a new contract",
        })
        print(f"  Closed old hedge {held.symbol} -> {close_result.status} "
              f"({close_result.order_id[:8]})")

    # A small limit buffer above the mid quote reduces the chance of the
    # paper order sitting unfilled if the market moves before it's seen --
    # this is a stated operational choice, not an attempt to game cost.
    limit_price = round(selection.estimated_premium_per_contract / 100.0 * 1.05, 2)
    open_result = broker.submit_option_order(
        symbol=c.symbol, qty=selection.contracts_to_buy, side="buy",
        position_intent="buy_to_open", order_type="limit",
        limit_price=limit_price,
    )
    record_hedge_trade({
        **base_row, "action": "open" if held is None else "roll_open",
        "qty": selection.contracts_to_buy, "side": "buy",
        "position_intent": "buy_to_open",
        "filled_avg_price": open_result.filled_avg_price,
        "order_id": open_result.order_id, "status": open_result.status,
        "dry_run": False, "note": "",
    })
    print(f"  Opened new hedge {c.symbol} x{selection.contracts_to_buy} "
          f"-> {open_result.status} ({open_result.order_id[:8]})")
    print("\nPAPER TRADING ONLY. No real money involved. "
          "No historical backtest exists for this strategy.")


if __name__ == "__main__":
    main()
