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
UP = pd.Series(np.linspace(100, 300, 300),
               index=pd.date_range(end="2026-11-09", periods=300))
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
    held = {"A": Position("A", 50, 5000, 100, 100, 0)}
    b2 = FakeBroker(positions=held)
    (tmp_path / "2").mkdir()
    (tmp_path / "2" / "s.json").write_text('{"peak_equity": 200000, "killed": true}')
    _run(tmp_path / "2", b2, {"A": DOWN}, _spec())
    assert b2.orders == [("A", 50, "sell", "day")]


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


import json


def test_daily_loss_halt_blocks_buys_allows_sells(tmp_path):
    (tmp_path / "s.json").write_text(
        '{"peak_equity": 100000, "day": "2026-11-10", "day_start_equity": 120000}')
    b = FakeBroker(equity=100_000.0)
    _run(tmp_path, b, {"A": UP}, _spec())
    assert b.orders == []
    held = {"A": Position("A", 50, 5000, 100, 100, 0)}
    b2 = FakeBroker(equity=100_000.0, positions=held)
    (tmp_path / "2").mkdir()
    (tmp_path / "2" / "s.json").write_text(
        '{"peak_equity": 100000, "day": "2026-11-10", "day_start_equity": 120000}')
    _run(tmp_path / "2", b2, {"A": DOWN}, _spec())
    assert b2.orders == [("A", 50, "sell", "day")]


def test_sell_never_exceeds_held_and_none_without_position(tmp_path):
    b = FakeBroker()
    _run(tmp_path, b, {"A": DOWN}, _spec())
    assert b.orders == []
    held = {"A": Position("A", 5, 500, 100, 100, 0)}
    b2 = FakeBroker(positions=held)
    _run(tmp_path / "2", b2, {"A": DOWN}, _spec())
    assert b2.orders == [("A", 5, "sell", "day")]


def test_dry_run_leaves_no_state_or_log_and_does_not_burn_session(tmp_path):
    b = FakeBroker()
    rows = _run(tmp_path, b, {"A": UP}, _spec(), dry_run=True)
    assert rows and not (tmp_path / "s.json").exists() and not (tmp_path / "log.csv").exists()
    _run(tmp_path, b, {"A": UP}, _spec())
    assert len(b.orders) == 1


class CrashBroker(FakeBroker):
    def submit_order(self, symbol, qty, side, time_in_force="day", **kw):
        if len(self.orders) == 1:
            raise RuntimeError("boom")
        self.kw = kw
        return super().submit_order(symbol, qty, side, time_in_force, **kw)


def test_crash_mid_loop_keeps_session_key_and_no_resend(tmp_path):
    reg = {"T": StrategySpec("T", ("A", "B"), "etf", 0.4,
                             lambda c: trend_signal(c, 50, 200), True)}
    b = CrashBroker()
    try:
        _run(tmp_path, b, {"A": UP, "B": UP}, reg, prices={"A": 100.0, "B": 100.0})
    except RuntimeError:
        pass
    assert "2026-11-10:open" in json.loads((tmp_path / "s.json").read_text())["ran"]
    n = len(b.orders)
    _run(tmp_path, b, {"A": UP, "B": UP}, reg, prices={"A": 100.0, "B": 100.0})
    assert len(b.orders) == n


def test_client_order_id_is_deterministic(tmp_path):
    seen = {}

    class B(FakeBroker):
        def submit_order(self, symbol, qty, side, time_in_force="day", **kw):
            seen.update(kw)
            return super().submit_order(symbol, qty, side, time_in_force)

    _run(tmp_path, B(), {"A": UP}, _spec())
    assert seen["client_order_id"] == "2026-11-10:open:A:buy"


def test_stop_loss_is_durable_until_signal_resets(tmp_path):
    held = {"A": Position("A", 50, 4500, 100, 90, -500)}
    b = FakeBroker(positions=held)
    _run(tmp_path, b, {"A": UP}, _spec(), prices={"A": 90.0})
    assert b.orders == [("A", 50, "sell", "day")]
    assert "A" in json.loads((tmp_path / "s.json").read_text())["stopped"]
    # session 2 (different name): signal still long, flat -> no buy
    b2 = FakeBroker()
    run = lambda broker, cl, name: run_session(
        name=name, broker=broker, closes=cl, now_utc=NOW, limits=SessionLimits(),
        state_path=tmp_path / "s.json", log_path=tmp_path / "log.csv", registry=_spec(),
        gate=lambda s: Verdict("ok", ""), prices={"A": 100.0}, dry_run=False)
    rows = run(b2, {"A": UP}, "mid")
    assert b2.orders == [] and rows[0]["note"] == "stopped out, waiting for signal reset"
    run(b2, {"A": DOWN}, "pm")
    assert "A" not in json.loads((tmp_path / "s.json").read_text())["stopped"]
    run(b2, {"A": UP}, "close")
    assert len(b2.orders) == 1 and b2.orders[0][2] == "buy"


def test_missing_data_holds_position_and_keeps_stopped(tmp_path):
    (tmp_path / "s.json").write_text(
        '{"peak_equity": 100000, "day": "2026-11-10", "stopped": {"A": "2026-11-05"}}')
    held = {"A": Position("A", 50, 5000, 100, 100, 0)}
    b = FakeBroker(positions=held)
    _run(tmp_path, b, {}, _spec())
    assert b.orders == []
    assert "A" in json.loads((tmp_path / "s.json").read_text())["stopped"]


def test_stale_data_holds_position_and_keeps_stopped(tmp_path):
    (tmp_path / "s.json").write_text(
        '{"peak_equity": 100000, "day": "2026-11-10", "stopped": {"A": "2026-11-05"}}')
    held = {"A": Position("A", 50, 5000, 100, 100, 0)}
    b = FakeBroker(positions=held)
    old = DOWN.iloc[:-10]          # last bar 10 days before today
    _run(tmp_path, b, {"A": old}, _spec())
    assert b.orders == []
    assert "A" in json.loads((tmp_path / "s.json").read_text())["stopped"]


def test_stop_loss_fires_even_with_missing_data(tmp_path):
    held = {"A": Position("A", 50, 4500, 100, 90, -500)}
    b = FakeBroker(positions=held)
    _run(tmp_path, b, {}, _spec(), prices={"A": 90.0})
    assert b.orders == [("A", 50, "sell", "day")]
    assert "A" in json.loads((tmp_path / "s.json").read_text())["stopped"]


def test_stale_state_blocks_buys_allows_sells(tmp_path):
    stale = '{"peak_equity": 100000, "day": "2026-11-01"}'
    (tmp_path / "s.json").write_text(stale)
    b = FakeBroker()
    rows = _run(tmp_path, b, {"A": UP}, _spec())
    assert b.orders == [] and rows[0]["note"] == "state file stale (possible lost kill-switch state)"
    (tmp_path / "2").mkdir()
    (tmp_path / "2" / "s.json").write_text(stale)
    held = {"A": Position("A", 50, 5000, 100, 100, 0)}
    b2 = FakeBroker(positions=held)
    _run(tmp_path / "2", b2, {"A": DOWN}, _spec())
    assert b2.orders == [("A", 50, "sell", "day")]


def test_stale_state_blocks_buys_in_dry_run(tmp_path):
    (tmp_path / "s.json").write_text('{"peak_equity": 100000, "day": "2026-11-01"}')
    rows = _run(tmp_path, FakeBroker(), {"A": UP}, _spec(), dry_run=True)
    assert rows[0]["side"] == "skip" and "stale" in rows[0]["note"]


def test_recent_state_allows_buys(tmp_path):
    (tmp_path / "s.json").write_text('{"peak_equity": 100000, "day": "2026-11-06"}')
    b = FakeBroker()
    _run(tmp_path, b, {"A": UP}, _spec())
    assert len(b.orders) == 1


def test_partial_sell_when_target_below_held(tmp_path):
    # target 5% of 100k = 5000; held 80 sh * $100 = 8000 -> sell 30, keep 50
    held = {"A": Position("A", 80, 8000, 100, 100, 0)}
    b = FakeBroker(positions=held)
    _run(tmp_path, b, {"A": UP}, _spec())
    assert b.orders == [("A", 30, "sell", "day")]
