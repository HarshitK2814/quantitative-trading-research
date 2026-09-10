"""H9: options protective-put overlay.

Pre-registered in ``research/hypotheses.md`` as a **forward-test-only**
hypothesis -- no free historical options-chain data exists back to 2007
(CBOE DataShop / OptionMetrics are paid), so this cannot be backtested the
way H1-H8 can. It runs live from day one with no prior validation. Every
report of this hypothesis's results must carry that disclosure -- it is not
a footnote to attach once.

Selection rule, stated here before any hedge is placed so it cannot be
quietly re-tuned after seeing a result:

* **Underlying:** SPY -- the largest single correlated exposure in the
  deployed book (three of the five H1 holdings are broad/sector equity).
* **Target strike:** the nearest available strike to 95% of the current
  underlying price (a ~5% out-of-the-money put). Cheaper than an
  at-the-money put while still capping the tail beyond a 5% decline.
* **Target expiry:** the nearest available expiry 21-35 days out; rolled
  once fewer than 14 days remain.
* **Coverage:** sized to the book's current *equity-sleeve* gross exposure
  (not total account equity, which includes cash and non-equity positions
  the hedge isn't protecting), rounded down to whole contracts.

Nothing here reacts to a loss or a gain. The rule is fixed; only the market
inputs (price, available strikes/expiries) change what it outputs on a given
day.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from src.broker import OptionContract, OptionQuote
from src.config import PORTFOLIO_DIR

if TYPE_CHECKING:
    from src.broker import AlpacaPaperBroker

logger = logging.getLogger(__name__)

TARGET_OTM_FRACTION: float = 0.05
MIN_DTE: int = 21
MAX_DTE: int = 35
ROLL_TRIGGER_DTE: int = 14

HEDGE_TRADES_PATH: Path = PORTFOLIO_DIR / "hedge_trades.csv"

_HEDGE_FIELDS = [
    "timestamp_utc", "trade_date", "action", "contract_symbol",
    "underlying_symbol", "option_type", "strike_price", "expiration_date",
    "qty", "side", "position_intent", "reference_mid_price",
    "filled_avg_price", "notional_covered", "gross_equity_exposure",
    "estimated_cost", "underlying_price_at_trade", "order_id", "status",
    "dry_run", "note",
]


@dataclass(frozen=True)
class HedgeSelection:
    """The contract chosen for a new or rolled hedge, and the sizing behind it."""

    contract: OptionContract
    contracts_to_buy: int
    notional_covered: float
    estimated_premium_per_contract: float  # dollars, i.e. quote.mid * 100
    estimated_total_cost: float


def expiry_window(as_of: date) -> tuple[date, date]:
    """Return the (min, max) expiration date to search, per the fixed rule."""
    return as_of + timedelta(days=MIN_DTE), as_of + timedelta(days=MAX_DTE)


def needs_roll(expiration_date: date, as_of: date) -> bool:
    """Whether a held hedge is close enough to expiry to need rolling."""
    return (expiration_date - as_of).days < ROLL_TRIGGER_DTE


def select_put_contract(
    contracts: list[OptionContract], underlying_price: float
) -> OptionContract | None:
    """Pick the contract closest to the pre-declared target strike.

    Args:
        contracts: Candidate puts, already filtered to the desired expiry
            window by the caller (:func:`expiry_window`).
        underlying_price: Current price of the underlying.

    Returns:
        The single best-matching contract, or ``None`` if the list is empty.

    """
    if not contracts or underlying_price <= 0:
        return None
    target_strike = underlying_price * (1.0 - TARGET_OTM_FRACTION)
    return min(contracts, key=lambda c: abs(c.strike_price - target_strike))


def size_hedge(
    gross_equity_exposure: float, contract: OptionContract
) -> tuple[int, float]:
    """Compute the number of contracts to buy and the notional they cover.

    Args:
        gross_equity_exposure: Dollar value of the book's equity-sleeve
            positions to protect (not total account equity -- cash and
            non-equity positions need no hedge).
        contract: The selected put contract.

    Returns:
        ``(contracts_to_buy, notional_covered)``. Rounds down, so coverage is
        never overstated -- the uncovered residual is the caller's to report,
        not to hide.

    """
    per_contract_notional = contract.strike_price * 100.0
    if per_contract_notional <= 0 or gross_equity_exposure <= 0:
        return 0, 0.0
    contracts_to_buy = int(gross_equity_exposure // per_contract_notional)
    return contracts_to_buy, contracts_to_buy * per_contract_notional


def plan_hedge(
    contracts: list[OptionContract],
    quotes: dict[str, OptionQuote],
    underlying_price: float,
    gross_equity_exposure: float,
) -> HedgeSelection | None:
    """Combine selection and sizing into one hedge decision.

    Returns:
        ``None`` if no contract could be selected, or sizing rounds to zero
        contracts (exposure too small to cover even one contract's worth).

    """
    contract = select_put_contract(contracts, underlying_price)
    if contract is None:
        return None

    contracts_to_buy, notional_covered = size_hedge(gross_equity_exposure, contract)
    if contracts_to_buy <= 0:
        return None

    quote = quotes.get(contract.symbol)
    premium_per_share = quote.mid if quote else 0.0
    premium_per_contract = premium_per_share * 100.0

    return HedgeSelection(
        contract=contract,
        contracts_to_buy=contracts_to_buy,
        notional_covered=notional_covered,
        estimated_premium_per_contract=premium_per_contract,
        estimated_total_cost=premium_per_contract * contracts_to_buy,
    )


def parse_occ_expiry(occ_symbol: str) -> date:
    """Extract the expiration date from a standard OCC option symbol.

    OCC symbols end in a fixed-width suffix regardless of the root ticker's
    length: 6-digit date (YYMMDD), 1-char C/P, 8-digit strike. E.g.
    ``"SPY261002P00725000"`` -> ``2026-10-02``.

    Args:
        occ_symbol: The option's OCC symbol.

    Returns:
        The contract's expiration date.

    Raises:
        ValueError: If the symbol is too short to contain the fixed suffix.

    """
    if len(occ_symbol) < 15:
        raise ValueError(f"Not a valid OCC option symbol: {occ_symbol!r}")
    tail = occ_symbol[-15:]
    yy, mm, dd = tail[0:2], tail[2:4], tail[4:6]
    return date(2000 + int(yy), int(mm), int(dd))


# ---------------------------------------------------------------------------
# Journal -- same append-only discipline as src/execution.py's trade journal.
# ---------------------------------------------------------------------------


def record_hedge_trade(row: dict) -> None:
    """Append one hedge event (open, roll, dry-run plan). Never overwritten."""
    HEDGE_TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
    is_new = not HEDGE_TRADES_PATH.exists() or HEDGE_TRADES_PATH.stat().st_size == 0
    with HEDGE_TRADES_PATH.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_HEDGE_FIELDS, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def load_hedge_trades() -> pd.DataFrame:
    """Load the hedge journal, or an empty frame if none exists yet."""
    if not HEDGE_TRADES_PATH.exists():
        return pd.DataFrame(columns=_HEDGE_FIELDS)
    return pd.read_csv(HEDGE_TRADES_PATH, parse_dates=["timestamp_utc"])


def update_hedge_fills(broker: AlpacaPaperBroker) -> int:
    """Re-poll open hedge orders and append a correction row with the real fill.

    H9's entire purpose is comparing actual premium paid against drawdown
    avoided, so a submission-time *estimate* left uncorrected would quietly
    undermine the one number this hypothesis exists to measure.

    Mirrors ``src/execution.py``'s ``update_fills`` -- including its fix:
    "still pending" is judged from each order's **most recent** journal row,
    not its first, so an order already confirmed filled is not rediscovered
    as pending on every future run and given a duplicate correction forever
    (see ``research/daily_log.md`` finding #24, the bug this was built to not
    repeat).

    Returns:
        Number of correction rows written.

    """
    trades = load_hedge_trades()
    if trades.empty:
        return 0

    submitted = trades[
        (trades["order_id"].astype(str).str.len() > 0)
        & (~trades["dry_run"].astype(str).str.lower().eq("true"))
    ]
    if submitted.empty:
        return 0

    latest_per_order = (
        submitted.sort_values("timestamp_utc").groupby("order_id").tail(1)
    )
    pending = latest_per_order[
        latest_per_order["status"].isin(
            ["accepted", "new", "pending_new", "partially_filled"]
        )
    ]

    written = 0
    for _, row in pending.iterrows():
        try:
            live = broker.get_order(str(row["order_id"]))
        except Exception as exc:  # noqa: BLE001 - a stale id must not stop the run
            logger.warning("Could not refresh option order %s: %s",
                           row["order_id"], exc)
            continue

        if live.get("status") != "filled":
            continue

        filled_price = (
            float(live["filled_avg_price"]) if live.get("filled_avg_price") else None
        )
        updated = row.to_dict()
        raw_note = row.get("note")
        note = "" if pd.isna(raw_note) else str(raw_note).strip()
        updated.update({
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "filled_avg_price": filled_price,
            "status": "filled",
            "note": f"{note} [fill update]".strip(),
        })
        record_hedge_trade(updated)
        written += 1

    return written
