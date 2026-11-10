"""Tests for the session orchestrator using a fake broker."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd

from src.broker import AccountSnapshot, Position
from src.intraday.groq_gate import Verdict
from src.intraday.limits import SessionLimits
from src.intraday.prices import to_yf
from src.intraday.session import run_session
from src.intraday.strategies import StrategySpec, trend_signal

NOW = datetime(2026, 11, 10, 14, 50, tzinfo=UTC)
UP = pd.Series(np.linspace(100, 300, 300), index=pd.date_range("2025-01-01", periods=300))
DOWN = UP[::-1].set_axis(UP.index)


class FakeBroker:
    def __init__(self, equity=100_000.0, positions=None, market_open=True):
        self.equity, self.positions, self.market_open = equity, positions or {}, market_open
        self.orders = []

    def get_account(self):
        return AccountSnapshot("a", self.equity, self.equity, self.equity, self.equity,
                               "ACTIVE", False, NOW)

    def get_positions(self):
        return self.positions

    def is_market_open(self):
        return self.market_open

    def submit_order(self, symbol, qty, side, time_in_force="day", **kw):
        self.orders.append((symbol, qty, side, time_in_force))
        return SimpleNamespace(order_id=f"id{len(self.orders)}")


def _spec(symbols=("A",), cls="etf", active=True):
    return {"T": StrategySpec("T", symbols, cls, 0.4,
                              lambda c: trend_signal(c, 50, 200), active)}


def _run(tmp_path, broker, closes, registry, gate=None, dry_run=False, prices=None):
    return run_session(
        name="open", broker=broker, closes=closes, now_utc=NOW,
        limits=SessionLimits(), state_path=tmp_path / "s.json",
        log_path=tmp_path / "log.csv", registry=registry,
        gate=gate or (lambda s: Verdict("ok", "")),
        prices=prices or {"A": 100.0}, dry_run=dry_run,
    )


def test_buy_sized_to_cap_and_logged(tmp_path):
    b = FakeBroker()
    rows = _run(tmp_path, b, {"A": UP}, _spec())
    assert b.orders == [("A", 50, "buy", "day")]      # 5% of 100k / $100
    assert rows[0]["side"] == "buy" and (tmp_path / "log.csv").exists()


def test_dry_run_places_no_orders(tmp_path):
    b = FakeBroker()
    rows = _run(tmp_path, b, {"A": UP}, _spec(), dry_run=True)
    assert b.orders == [] and rows[0]["dry_run"] is True


def test_veto_blocks_buy_but_not_sell(tmp_path):
    b = FakeBroker()
    _run(tmp_path, b, {"A": UP}, _spec(), gate=lambda s: Verdict("veto", "bad"))
    assert b.orders == []
    held = {"A": Position("A", 50, 5000, 100, 100, 0)}
    b2 = FakeBroker(positions=held)
    _run(tmp_path / "2", b2, {"A": DOWN}, _spec(), gate=lambda s: Verdict("veto", "bad"))
    assert b2.orders == [("A", 50, "sell", "day")]


def test_reduce_halves_buy(tmp_path):
    b = FakeBroker()
    _run(tmp_path, b, {"A": UP}, _spec(), gate=lambda s: Verdict("reduce", "mixed"))
    assert b.orders[0][1] == 25


def test_stop_loss_forces_exit_even_if_signal_long(tmp_path):
    held = {"A": Position("A", 50, 4500, 100, 90, -500)}   # -10% > 8% stop
    b = FakeBroker(positions=held)
    _run(tmp_path, b, {"A": UP}, _spec(), prices={"A": 90.0})
    assert b.orders == [("A", 50, "sell", "day")]


def test_kill_switch_blocks_buys_allows_sells(tmp_path):
    (tmp_path / "s.json").write_text('{"peak_equity": 200000, "killed": true}')
    b = FakeBroker()
    _run(tmp_path, b, {"A": UP}, _spec())
    assert b.orders == []


def test_stocks_skipped_when_market_closed_crypto_trades(tmp_path):
    b = FakeBroker(market_open=False)
    reg = {**_spec(("A",), "etf"), "C": StrategySpec(
        "C", ("BTC/USD",), "crypto", 0.3, lambda c: trend_signal(c, 50, 200), True)}
    _run(tmp_path, b, {"A": UP, "BTC/USD": UP}, reg, prices={"A": 100.0, "BTC/USD": 50_000.0})
    assert [o[0] for o in b.orders] == ["BTC/USD"]
    assert b.orders[0][3] == "gtc" and b.orders[0][1] == 0.1   # 5% of 100k / 50k


def test_session_runs_once_per_day(tmp_path):
    b = FakeBroker()
    _run(tmp_path, b, {"A": UP}, _spec())
    _run(tmp_path, b, {"A": UP}, _spec())
    assert len(b.orders) == 1


def test_untracked_positions_are_never_touched(tmp_path):
    held = {"ZZZ": Position("ZZZ", 10, 1000, 100, 100, 0)}
    b = FakeBroker(positions=held)
    _run(tmp_path, b, {"A": UP}, _spec())
    assert all(o[0] != "ZZZ" for o in b.orders)


def test_to_yf_maps_crypto():
    assert to_yf("BTC/USD") == "BTC-USD" and to_yf("SPY") == "SPY"
