"""Tests for the trade journal's fill-polling logic.

Regression coverage for the bug in research/daily_log.md finding #24:
update_fills judged "still pending" off each order's *original* append-only
row, which never changes, so an already-filled order was rediscovered as
pending on every subsequent run and given another duplicate correction row
forever. These tests run against a fake broker; no network call is made.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src import execution
from src.broker import OrderResult
from src.execution import PlannedOrder, load_trades, record_trade, update_fills


class _FakeBroker:
    """Returns a canned order state; never touches the network."""

    def __init__(self, order_state: dict) -> None:
        self._state = order_state
        self.calls = 0

    def get_order(self, order_id: str) -> dict:
        self.calls += 1
        return self._state


def _order(symbol: str = "SPY") -> PlannedOrder:
    return PlannedOrder(
        symbol=symbol, side="buy", qty=10, reference_price=100.0,
        current_weight=0.0, target_weight=0.2, weight_delta=0.2,
        notional=1000.0, reason="increase to target",
    )


def _submit(symbol: str = "SPY") -> OrderResult:
    return OrderResult(
        order_id="order-1", client_order_id="coid-1", symbol=symbol,
        side="buy", qty=10, order_type="market", time_in_force="day",
        status="accepted", submitted_at="2026-09-09T00:00:00Z",
        filled_qty=0.0, filled_avg_price=None,
    )


@pytest.fixture(autouse=True)
def _isolated_journal(tmp_path, monkeypatch):
    """Point the journal at a scratch file for every test in this module."""
    trades_path = tmp_path / "trades.csv"
    monkeypatch.setattr("src.execution.TRADES_PATH", trades_path)
    return trades_path


def test_pending_order_gets_one_correction_row_when_filled() -> None:
    record_trade(_order(), _submit(), "TEST-STRAT", 100_000.0)
    broker = _FakeBroker(
        {"status": "filled", "filled_avg_price": "101.5", "filled_qty": "10"}
    )
    written = update_fills(broker)
    assert written == 1

    trades = pd.read_csv(execution.TRADES_PATH)
    assert (trades["status"] == "filled").sum() == 1


def test_already_filled_order_is_not_repolled() -> None:
    """The core regression: a second run must not add a second correction."""
    record_trade(_order(), _submit(), "TEST-STRAT", 100_000.0)
    broker = _FakeBroker(
        {"status": "filled", "filled_avg_price": "101.5", "filled_qty": "10"}
    )

    first_pass = update_fills(broker)
    second_pass = update_fills(broker)

    assert first_pass == 1
    assert second_pass == 0  # already-filled order must not be rediscovered
    assert broker.calls == 1  # the network call itself only happens once


def test_still_open_order_is_left_alone() -> None:
    record_trade(_order(), _submit(), "TEST-STRAT", 100_000.0)
    broker = _FakeBroker({"status": "accepted", "filled_avg_price": None,
                          "filled_qty": "0"})
    assert update_fills(broker) == 0


def test_dry_run_orders_are_never_polled() -> None:
    record_trade(_order(), None, "TEST-STRAT", 100_000.0, dry_run=True)
    broker = _FakeBroker({"status": "filled", "filled_avg_price": "100.0",
                          "filled_qty": "10"})
    assert update_fills(broker) == 0
    assert broker.calls == 0


# ---------------------------------------------------------------------------
# load_trades(deduplicate=True)
# ---------------------------------------------------------------------------


def test_deduplicate_collapses_repeated_identical_correction_rows() -> None:
    """Reproduces finding #24's artefact directly and confirms it collapses."""
    record_trade(_order(), _submit(), "TEST-STRAT", 100_000.0)
    identical_fill = {"status": "filled", "filled_avg_price": "101.5",
                      "filled_qty": "10"}
    # Simulate the pre-fix bug: three runs each append the same correction.
    for _ in range(3):
        row = pd.read_csv(execution.TRADES_PATH).iloc[-1].to_dict()
        row["timestamp_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
        row.update(identical_fill)
        row["filled_avg_price"] = float(identical_fill["filled_avg_price"])
        row["filled_qty"] = float(identical_fill["filled_qty"])
        execution._append_row(execution.TRADES_PATH, execution._TRADE_FIELDS, row)

    raw = load_trades(deduplicate=False)
    deduped = load_trades(deduplicate=True)
    assert len(raw) == 4  # 1 original submission + 3 duplicated corrections
    assert len(deduped) == 2  # 1 submission + 1 collapsed correction


def test_deduplicate_preserves_distinct_orders() -> None:
    record_trade(_order("SPY"), _submit("SPY"), "TEST-STRAT", 100_000.0)
    record_trade(_order("QQQ"), _submit("QQQ"), "TEST-STRAT", 100_000.0)
    deduped = load_trades(deduplicate=True)
    assert len(deduped) == 2
    assert set(deduped["symbol"]) == {"SPY", "QQQ"}
