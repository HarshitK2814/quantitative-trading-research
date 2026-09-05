"""Order generation and the trade journal.

Turns a risk-approved target weight vector into concrete orders by
reconciling against **actual broker positions** rather than against what the
system believes it holds. Reconciling to reality is what stops a missed fill,
a partial fill, or a manual intervention from silently compounding into a
position the strategy never intended.

Journal design
--------------
Two files, both append-only:

* ``portfolio/trades.csv`` -- one row per order, recording the intended price
  at generation time alongside the achieved fill. The difference between those
  two is **measured slippage**, which is the only way to check the 10bps cost
  assumption used throughout the backtests against reality.
* ``portfolio/daily_snapshot.csv`` -- one row per day of portfolio state.

Neither file is ever rewritten. Correcting history would destroy the evidence
trail the project exists to produce.
"""

from __future__ import annotations

import csv
import logging
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.broker import AlpacaPaperBroker, Position
from src.config import PORTFOLIO_DIR, RISK

logger = logging.getLogger(__name__)

TRADES_PATH = PORTFOLIO_DIR / "trades.csv"
SNAPSHOT_PATH = PORTFOLIO_DIR / "daily_snapshot.csv"


@dataclass
class PlannedOrder:
    """One intended order, before submission."""

    symbol: str
    side: str
    qty: int
    reference_price: float
    current_weight: float
    target_weight: float
    weight_delta: float
    notional: float
    reason: str


def plan_orders(
    target_weights: pd.Series,
    positions: dict[str, Position],
    equity: float,
    prices: dict[str, float],
    min_notional: float = RISK.min_trade_notional_usd,
) -> list[PlannedOrder]:
    """Reconcile target weights against actual positions and produce orders.

    Args:
        target_weights: Risk-approved target weights by symbol.
        positions: Current broker positions by symbol.
        equity: Current account equity.
        prices: Latest price per symbol.
        min_notional: Orders below this dollar value are suppressed.

    Returns:
        Orders to submit. Sells are ordered before buys so that proceeds are
        available before purchases settle -- without this, a fully-invested
        rebalance can be rejected for insufficient buying power.

    Note:
        Quantities are **whole shares**, rounded toward zero. This leaves small
        residual weight errors (a $770 SPY share cannot express an arbitrary
        percentage of a $100k book) which are recorded rather than corrected.
        Fractional-share orders would reduce the error but introduce their own
        fill semantics, and the residual is small enough to measure and report.

    """
    if equity <= 0:
        return []

    orders: list[PlannedOrder] = []
    symbols = sorted(set(target_weights.index) | set(positions))

    for symbol in symbols:
        target_weight = float(target_weights.get(symbol, 0.0) or 0.0)
        position = positions.get(symbol)
        current_qty = position.qty if position else 0.0

        price = prices.get(symbol) or (position.current_price if position else None)
        if not price or price <= 0:
            logger.warning("No usable price for %s; skipping.", symbol)
            continue

        current_value = current_qty * price
        current_weight = current_value / equity
        target_qty_exact = (target_weight * equity) / price

        # Round toward zero so rounding never increases exposure.
        target_qty = int(math.floor(target_qty_exact))
        delta_qty = target_qty - int(current_qty)

        if delta_qty == 0:
            continue

        notional = abs(delta_qty) * price
        if notional < min_notional:
            logger.debug(
                "Suppressing dust trade %s %s (%.2f < %.2f)",
                symbol, delta_qty, notional, min_notional,
            )
            continue

        orders.append(
            PlannedOrder(
                symbol=symbol,
                side="buy" if delta_qty > 0 else "sell",
                qty=abs(delta_qty),
                reference_price=float(price),
                current_weight=round(current_weight, 6),
                target_weight=round(target_weight, 6),
                weight_delta=round(target_weight - current_weight, 6),
                notional=round(notional, 2),
                reason=(
                    "increase to target" if delta_qty > 0 else "reduce to target"
                ),
            )
        )

    # Sells first: free the cash before spending it.
    orders.sort(key=lambda o: (o.side != "sell", o.symbol))
    return orders


def estimate_turnover(orders: list[PlannedOrder], equity: float) -> float:
    """Estimate one-way turnover implied by a set of planned orders."""
    if equity <= 0:
        return 0.0
    return float(sum(o.notional for o in orders) / equity)


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------

_TRADE_FIELDS = [
    "timestamp_utc", "trade_date", "strategy_version", "symbol", "side", "qty",
    "order_type", "time_in_force", "reference_price", "filled_avg_price",
    "filled_qty", "slippage_bps", "notional", "current_weight", "target_weight",
    "weight_delta", "reason", "order_id", "client_order_id", "status",
    "account_equity", "dry_run",
]

_SNAPSHOT_FIELDS = [
    "date", "timestamp_utc", "strategy_version", "equity", "last_equity", "cash",
    "daily_return", "cumulative_return", "drawdown", "gross_exposure",
    "net_exposure", "cash_weight", "n_positions", "max_position_weight",
    "positions_json", "benchmark_spy", "notes",
]


def _append_row(path: Path, fields: list[str], row: dict) -> None:
    """Append one row, writing a header if the file is new."""
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def compute_slippage_bps(
    reference_price: float, filled_price: float | None, side: str
) -> float | None:
    """Return realised slippage in basis points, signed so positive is worse.

    A buy filled above the reference price, or a sell filled below it, both
    count as positive (adverse) slippage. This is the quantity the project's
    assumed 10bps cost model is supposed to approximate, and the live period
    exists partly to check whether it does.
    """
    if not filled_price or not reference_price or reference_price <= 0:
        return None
    direction = 1.0 if side == "buy" else -1.0
    return round(
        direction * (filled_price - reference_price) / reference_price * 10_000.0, 3
    )


def record_trade(
    order: PlannedOrder,
    result,
    strategy_version: str,
    account_equity: float,
    dry_run: bool = False,
) -> None:
    """Append one order to the trade journal.

    Args:
        order: The planned order.
        result: An ``OrderResult``, or ``None`` for a dry run.
        strategy_version: Identifier of the deployed strategy version.
        account_equity: Equity at submission time.
        dry_run: True when no order was actually sent.

    """
    now = datetime.now(UTC)
    filled_price = getattr(result, "filled_avg_price", None) if result else None

    _append_row(
        TRADES_PATH,
        _TRADE_FIELDS,
        {
            "timestamp_utc": now.isoformat(),
            "trade_date": now.date().isoformat(),
            "strategy_version": strategy_version,
            "symbol": order.symbol,
            "side": order.side,
            "qty": order.qty,
            "order_type": getattr(result, "order_type", "market") if result else "market",
            "time_in_force": getattr(result, "time_in_force", "day") if result else "day",
            "reference_price": order.reference_price,
            "filled_avg_price": filled_price,
            "filled_qty": getattr(result, "filled_qty", 0.0) if result else 0.0,
            "slippage_bps": compute_slippage_bps(
                order.reference_price, filled_price, order.side
            ),
            "notional": order.notional,
            "current_weight": order.current_weight,
            "target_weight": order.target_weight,
            "weight_delta": order.weight_delta,
            "reason": order.reason,
            "order_id": getattr(result, "order_id", "") if result else "",
            "client_order_id": getattr(result, "client_order_id", "") if result else "",
            "status": getattr(result, "status", "DRY_RUN") if result else "DRY_RUN",
            "account_equity": round(account_equity, 2),
            "dry_run": dry_run,
        },
    )


def record_snapshot(row: dict) -> None:
    """Append one daily portfolio snapshot."""
    _append_row(SNAPSHOT_PATH, _SNAPSHOT_FIELDS, row)


def load_snapshots(deduplicate: bool = True) -> pd.DataFrame:
    """Load the snapshot history, or an empty frame if none exists yet.

    Args:
        deduplicate: Keep only the last snapshot per calendar date. The file is
            append-only, so running the script more than once in a day (a dry
            run followed by an execution, say) legitimately writes several rows
            for that date. Every one is a truthful record of the moment it was
            taken, but a return series must use one observation per day or it
            will double-count. Pass ``False`` to inspect the raw audit trail.

    Returns:
        Snapshot history sorted by date.

    """
    if not SNAPSHOT_PATH.exists():
        return pd.DataFrame(columns=_SNAPSHOT_FIELDS)
    frame = pd.read_csv(SNAPSHOT_PATH, parse_dates=["date"])
    frame = frame.sort_values(["date", "timestamp_utc"])
    if deduplicate:
        frame = frame.drop_duplicates(subset="date", keep="last")
    return frame.reset_index(drop=True)


def load_trades() -> pd.DataFrame:
    """Load the trade journal, or an empty frame if none exists yet."""
    if not TRADES_PATH.exists():
        return pd.DataFrame(columns=_TRADE_FIELDS)
    return pd.read_csv(TRADES_PATH, parse_dates=["timestamp_utc"])


def update_fills(broker: AlpacaPaperBroker) -> int:
    """Re-poll open journal rows and write a corrected fill row for each.

    Market orders submitted while the market is closed sit as ``accepted`` and
    fill at the next open, so the journal's first row for such an order has no
    fill price. This adds a **new** row with the achieved fill rather than
    editing the original, keeping the journal append-only and preserving the
    record of what was known at submission time.

    Returns:
        Number of correction rows written.

    """
    trades = load_trades()
    if trades.empty:
        return 0

    pending = trades[
        (trades["status"].isin(["accepted", "new", "pending_new", "partially_filled"]))
        & (trades["order_id"].astype(str).str.len() > 0)
        & (~trades["dry_run"].astype(str).str.lower().eq("true"))
    ]

    written = 0
    for _, row in pending.iterrows():
        try:
            live = broker.get_order(str(row["order_id"]))
        except Exception as exc:  # noqa: BLE001 - a stale id must not stop the run
            logger.warning("Could not refresh order %s: %s", row["order_id"], exc)
            continue

        if live.get("status") != "filled":
            continue

        filled_price = (
            float(live["filled_avg_price"]) if live.get("filled_avg_price") else None
        )
        updated = row.to_dict()
        updated.update(
            {
                "timestamp_utc": datetime.now(UTC).isoformat(),
                "filled_avg_price": filled_price,
                "filled_qty": float(live.get("filled_qty") or 0.0),
                "slippage_bps": compute_slippage_bps(
                    float(row["reference_price"]), filled_price, str(row["side"])
                ),
                "status": "filled",
                "reason": f"{row['reason']} [fill update]",
            }
        )
        _append_row(TRADES_PATH, _TRADE_FIELDS, updated)
        written += 1

    return written


def planned_orders_frame(orders: list[PlannedOrder]) -> pd.DataFrame:
    """Render planned orders as a DataFrame for display."""
    if not orders:
        return pd.DataFrame(
            columns=list(PlannedOrder.__dataclass_fields__)
        )
    return pd.DataFrame([asdict(o) for o in orders])
