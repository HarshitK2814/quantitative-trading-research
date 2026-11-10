"""Options session step (O1/O2) with an offline fake broker."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd

from src.broker import AccountSnapshot, OptionContract, OptionQuote, Position
from src.intraday.groq_gate import Verdict
from src.intraday.limits import SessionLimits, load_state
from src.intraday.options_session import run_options
from src.intraday.session import run_session
from src.intraday.strategies import REGISTRY

NOW = datetime(2026, 11, 10, 16, 35, tzinfo=UTC)     # 11:35 ET
TODAY = date(2026, 11, 10)
EXP = TODAY + timedelta(days=35)
UP = pd.Series(np.linspace(100, 300, 300),
               index=pd.date_range(end="2026-11-09", periods=300))
DOWN = UP[::-1].set_axis(UP.index)
MIDS = {85: (0.30, 0.40), 90: (0.80, 0.90), 95: (2.00, 2.10), 100: (4.00, 4.20)}


def occ(und, k, exp=EXP):
    return f"{und}{exp:%y%m%d}P{int(k * 1000):08d}"


def chain_quotes(age_min=1):
    out = {}
    for und in ("SPY", "QQQ"):
        for k, (b, a) in MIDS.items():
            s = occ(und, k)
            out[s] = OptionQuote(s, b, a, NOW - timedelta(minutes=age_min))
    return out


class OptBroker:
    def __init__(self, quotes=None, positions=None, reject_mleg=False,
                 state_path=None, order_status=None, mleg_error=None,
                 by_client=None, open_orders=None):
        self.quotes = chain_quotes() if quotes is None else quotes
        self.positions = positions or {}
        self.reject_mleg = reject_mleg
        self.mleg_error = mleg_error
        self.by_client = by_client or {}
        self.open_orders = open_orders or []
        self.state_path = state_path
        self.order_status = order_status or {}
        self.spread_orders, self.option_orders, self.state_at_submit = [], [], []

    def _snap(self):
        p = self.state_path
        self.state_at_submit.append(json.loads(p.read_text()) if p and p.exists() else None)

    def get_option_contracts(self, und, typ, lo, hi, strike_gte=None, strike_lte=None,
                             limit=100):
        if not lo <= EXP <= hi:
            return []
        return [OptionContract(occ(und, k), und, "put", float(k), EXP, True)
                for k in MIDS]

    def get_option_quotes(self, syms):
        return {s: self.quotes[s] for s in syms if s in self.quotes}

    def get_option_positions(self):
        return self.positions

    def submit_spread_order(self, legs, qty, limit_price, client_order_id=None,
                            time_in_force="day"):
        self._snap()
        if self.reject_mleg:
            raise RuntimeError("Alpaca POST /v2/orders failed: HTTP 422 mleg")
        if self.mleg_error:
            raise self.mleg_error
        self.spread_orders.append((legs, qty, limit_price, client_order_id))
        return SimpleNamespace(order_id=f"sp{len(self.spread_orders)}")

    def submit_option_order(self, symbol, qty, side, position_intent,
                            order_type="limit", limit_price=None,
                            time_in_force="day", client_order_id=None):
        self._snap()
        self.option_orders.append((symbol, qty, side, position_intent, order_type,
                                   limit_price, client_order_id))
        return SimpleNamespace(order_id=f"op{len(self.option_orders)}")

    def get_order(self, oid):
        return self.order_status.get(oid, {"status": "new"})

    def get_order_by_client_id(self, coid):
        if coid in self.by_client:
            return self.by_client[coid]
        raise RuntimeError("Alpaca GET failed: HTTP 404 not found")

    def get_orders(self, status="all", limit=100, after=None, nested=False):
        return self.open_orders


def _run(tmp_path, broker, *, state=None, allowed=True, session="late_morning",
         action="ok", closes=None, eq_pos=None, dry_run=False, market_open=True,
         now=NOW):
    state = {"options": {}} if state is None else state
    rows = []

    def emit(sym, side, qty, price, verdict=None, note="", order_id="", strategy=None):
        rows.append({"symbol": sym, "side": side, "qty": qty, "price": price,
                     "note": note, "strategy": strategy, "order_id": order_id,
                     "news": getattr(verdict, "action", "")})

    run_options(
        key=f"{now.date().isoformat()}:{session}", session=session, broker=broker,
        state=state,
        equity=100_000.0, closes=closes or {"SPY": UP, "QQQ": UP},
        registry=REGISTRY, gate=lambda s: Verdict(action, "r"),
        prices={"SPY": 100.0, "QQQ": 100.0}, now_utc=now, allowed=allowed,
        why="ok" if allowed else "kill switch active", market_open=market_open,
        dry_run=dry_run, state_path=tmp_path / "s.json",
        equity_positions=eq_pos or {}, emit=emit,
    )
    return state, rows


def _open_spread(und="SPY", credit=2.40, exp=EXP):
    return {"underlying": und, "short": occ(und, 95, exp), "long": occ(und, 90, exp),
            "width": 5.0, "credit": credit, "contracts": 1,
            "expiry": exp.isoformat(), "max_loss": (5 - credit) * 100,
            "status": "open", "order_id": "old"}


def _legs_pos(und="SPY", exp=EXP):
    s, lg = occ(und, 95, exp), occ(und, 90, exp)
    return {s: Position(s, -1, -200, 2.4, 2.0, 0), lg: Position(lg, 1, 80, 1, 0.8, 0)}


# -- O2 opens -------------------------------------------------------------------

def test_spread_opens_as_one_mleg_order_and_state_saved_first(tmp_path):
    b = OptBroker(state_path=tmp_path / "s.json")
    state, rows = _run(tmp_path, b)
    assert len(b.spread_orders) == 1 and b.option_orders == []
    legs, qty, limit, coid = b.spread_orders[0]
    assert [(lg["side"], lg["position_intent"]) for lg in legs] == [
        ("sell", "sell_to_open"), ("buy", "buy_to_open")]
    assert legs[0]["symbol"] == occ("SPY", 95) and legs[1]["symbol"] == occ("SPY", 90)
    assert qty == 2 and limit == -1.20                   # 2 x 380 <= 1% of 100k
    assert coid == "2026-11-10:late_morning:O2:SPY:open"
    saved = b.state_at_submit[0]["options"]["spreads"]
    assert list(saved.values())[0]["status"] == "pending_open"
    sp = state["options"]["spreads"]["2026-11-10:SPY"]
    assert sp["order_id"] == "sp1" and sp["max_loss"] == 760.0
    o2 = [r for r in rows if r["strategy"] == "O2" and r["side"] == "sell_spread"]
    assert "max_loss=760" in o2[0]["note"] and occ("SPY", 90) in o2[0]["note"]


def test_second_etf_blocked_by_spread_risk_bucket(tmp_path):
    b = OptBroker()
    _, rows = _run(tmp_path, b)
    assert len(b.spread_orders) == 1                     # QQQ would breach 1%
    assert any(r["symbol"] == "QQQ" and "budget" in r["note"] for r in rows)


def test_no_spread_when_news_reduce_or_veto(tmp_path):
    for action in ("reduce", "veto"):
        b = OptBroker()
        _run(tmp_path / action, b, action=action)
        assert b.spread_orders == []


def test_no_spread_when_trend_not_long(tmp_path):
    b = OptBroker()
    _run(tmp_path, b, closes={"SPY": DOWN, "QQQ": DOWN})
    assert b.spread_orders == []


def test_no_spread_when_two_already_open(tmp_path):
    state = {"options": {"spreads": {"a": {**_open_spread(), "max_loss": 100.0},
                                     "b": {**_open_spread(), "max_loss": 100.0}}}}
    pos = _legs_pos()
    b = OptBroker(positions=pos, quotes={})          # no quotes -> no closes either
    _run(tmp_path, b, state=state)
    assert b.spread_orders == []


def test_total_risk_cap_blocks_all_new_opens(tmp_path):
    hedge_sym = occ("SPY", 85)
    state = {"options": {
        "hedges": {hedge_sym: {"qty": 1, "cost_basis": 1000.0, "expiry": EXP.isoformat(),
                               "status": "open", "order_id": "h"}},
        "spreads": {"a": {**_open_spread(), "max_loss": 1000.0}}}}
    hedge_pos = Position(hedge_sym, 1, 200, 2.0, 2.0, 0)
    b = OptBroker(positions={**_legs_pos(), hedge_sym: hedge_pos}, quotes={})
    _, rows = _run(tmp_path, b, state=state,
                   eq_pos={"SPY": Position("SPY", 300, 30_000, 100, 100, 0)})
    assert b.spread_orders == [] and b.option_orders == []
    assert any("2%" in r["note"] for r in rows)


def test_stale_or_missing_quotes_skip_not_trade(tmp_path):
    b = OptBroker(quotes=chain_quotes(age_min=60))
    _, rows = _run(tmp_path, b)
    assert b.spread_orders == []
    assert any("quote" in r["note"] for r in rows)
    b2 = OptBroker(quotes={})
    _run(tmp_path / "2", b2)
    assert b2.spread_orders == []


def test_mleg_rejected_skips_and_logs_without_single_leg_fallback(tmp_path):
    b = OptBroker(reject_mleg=True, state_path=tmp_path / "s.json")
    state, rows = _run(tmp_path, b)
    assert b.option_orders == []                         # never two single legs
    assert state["options"]["spreads"] == {}
    assert any("rejected" in r["note"] for r in rows)
    assert load_state(tmp_path / "s.json")["options"]["spreads"] == {}


def test_dry_run_places_nothing_and_saves_nothing(tmp_path):
    b = OptBroker()
    _, rows = _run(tmp_path, b, dry_run=True)
    assert b.spread_orders == [] and b.option_orders == []
    assert not (tmp_path / "s.json").exists()
    assert any(r["side"] == "sell_spread" for r in rows)


def test_only_late_morning_and_market_open(tmp_path):
    b = OptBroker()
    _run(tmp_path, b, session="open")
    _run(tmp_path / "2", b, market_open=False)
    assert b.spread_orders == [] and b.option_orders == []


# -- closes ---------------------------------------------------------------------

def _close_quotes(short_mid_bid, short_ask, long_bid, long_ask):
    s, lg = occ("SPY", 95), occ("SPY", 90)
    t = NOW - timedelta(minutes=1)
    return {s: OptionQuote(s, short_mid_bid, short_ask, t),
            lg: OptionQuote(lg, long_bid, long_ask, t)}


def test_profit_close_allowed_even_when_killed(tmp_path):
    state = {"options": {"spreads": {"x": _open_spread(credit=2.40)}}}
    b = OptBroker(positions=_legs_pos(), quotes=_close_quotes(1.15, 1.25, 0.0, 0.10))
    state, _ = _run(tmp_path, b, state=state, allowed=False)
    assert len(b.spread_orders) == 1
    legs, qty, limit, coid = b.spread_orders[0]
    assert [(lg["side"], lg["position_intent"]) for lg in legs] == [
        ("buy", "buy_to_close"), ("sell", "sell_to_close")]
    assert limit == 1.25 and qty == 1 and coid.endswith("O2:x:close")
    assert state["options"]["spreads"]["x"]["status"] == "pending_close"


def test_stop_close_at_2x_credit(tmp_path):
    state = {"options": {"spreads": {"x": _open_spread(credit=1.0)}}}
    b = OptBroker(positions=_legs_pos(), quotes=_close_quotes(2.40, 2.50, 0.30, 0.40))
    _, rows = _run(tmp_path, b, state=state, closes={"SPY": DOWN, "QQQ": DOWN})
    assert len(b.spread_orders) == 1 and any("stop" in r["note"] for r in rows)


def test_dte_close_at_7_days(tmp_path):
    exp = TODAY + timedelta(days=7)
    sp = _open_spread(exp=exp)
    s, lg = sp["short"], sp["long"]
    t = NOW - timedelta(minutes=1)
    q = {s: OptionQuote(s, 2.0, 2.1, t), lg: OptionQuote(lg, 0.8, 0.9, t)}
    b = OptBroker(positions=_legs_pos(exp=exp), quotes=q)
    _, rows = _run(tmp_path, b, state={"options": {"spreads": {"x": sp}}},
                   closes={"SPY": DOWN, "QQQ": DOWN})
    assert len(b.spread_orders) == 1 and any("dte" in r["note"] for r in rows)


def test_close_due_but_no_quote_skips(tmp_path):
    exp = TODAY + timedelta(days=5)
    b = OptBroker(positions=_legs_pos(exp=exp), quotes={})
    _, rows = _run(tmp_path, b, state={"options": {"spreads": {"x": _open_spread(exp=exp)}}},
                   closes={"SPY": DOWN, "QQQ": DOWN})
    assert b.spread_orders == [] and any("no fresh quote" in r["note"] for r in rows)


def test_untracked_option_positions_are_never_touched(tmp_path):
    other = occ("SPY", 72000 / 1000)
    pos = {other: Position(other, 2, 300, 1.5, 1.5, 0)}
    b = OptBroker(positions=pos, quotes={})
    _run(tmp_path, b, allowed=False)
    assert b.spread_orders == [] and b.option_orders == []


def test_filled_close_removes_spread(tmp_path):
    sp = {**_open_spread(), "status": "pending_close", "close_order_id": "c1"}
    b = OptBroker(order_status={"c1": {"status": "filled", "filled_qty": "1"}},
                  quotes={})
    state, _ = _run(tmp_path, b, state={"options": {"spreads": {"x": sp}}},
                    allowed=False)
    assert state["options"]["spreads"] == {}


# -- O1 hedge -------------------------------------------------------------------

def test_hedge_opens_capped_at_1pct_premium(tmp_path):
    b = OptBroker(quotes={k: v for k, v in chain_quotes().items() if k.startswith("SPY")})
    eq = {"SPY": Position("SPY", 1000, 100_000, 100, 100, 0)}       # 10 contracts by size
    state, _ = _run(tmp_path, b, eq_pos=eq, closes={"SPY": DOWN, "QQQ": DOWN})
    assert len(b.option_orders) == 1
    sym, qty, side, intent, otype, limit, coid = b.option_orders[0]
    assert (sym, side, intent, otype) == (occ("SPY", 95), "buy", "buy_to_open", "limit")
    assert limit == round(2.05 * 1.05, 2) and qty == 4               # 4 x 215 <= 1000
    assert coid == f"2026-11-10:late_morning:O1:{sym}:open"
    assert state["options"]["hedges"][sym]["cost_basis"] <= 1000.0


def test_hedge_not_opened_when_killed(tmp_path):
    b = OptBroker()
    eq = {"SPY": Position("SPY", 1000, 100_000, 100, 100, 0)}
    _run(tmp_path, b, eq_pos=eq, allowed=False)
    assert b.option_orders == [] and b.spread_orders == []


def test_hedge_rolls_by_closing_when_inside_14_dte(tmp_path):
    exp = TODAY + timedelta(days=10)
    h = occ("SPY", 95, exp)
    t = NOW - timedelta(minutes=1)
    state = {"options": {"hedges": {h: {"qty": 2, "cost_basis": 400.0,
                                        "expiry": exp.isoformat(), "status": "open",
                                        "order_id": "h1"}}}}
    b = OptBroker(positions={h: Position(h, 2, 100, 2.0, 0.5, -300)},
                  quotes={h: OptionQuote(h, 0.45, 0.55, t)})
    state, _ = _run(tmp_path, b, state=state, allowed=False)
    assert b.option_orders[0][:5] == (h, 2, "sell", "sell_to_close", "limit")
    assert b.option_orders[0][5] == 0.45
    assert state["options"]["hedges"][h]["status"] == "pending_close"


# -- wiring into run_session ----------------------------------------------------

class SessBroker(OptBroker):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.equity_orders = []

    def get_account(self):
        return AccountSnapshot("a", 100_000.0, 100_000.0, 100_000.0, 100_000.0,
                               "ACTIVE", False, NOW)

    def get_positions(self):
        return {}

    def is_market_open(self):
        return True

    def submit_order(self, symbol, qty, side, time_in_force="day", **kw):
        self.equity_orders.append((symbol, qty, side))
        return SimpleNamespace(order_id="e")


def _session(tmp_path, b, name):
    return run_session(
        name=name, broker=b, closes={"SPY": UP, "QQQ": UP}, now_utc=NOW,
        limits=SessionLimits(), state_path=tmp_path / "s.json",
        log_path=tmp_path / "log.csv", registry={"S1": REGISTRY["S1"]},
        gate=lambda s: Verdict("ok", ""), prices={"SPY": 100.0, "QQQ": 100.0},
        dry_run=False, options=True,
    )


def test_run_session_runs_options_in_late_morning_only(tmp_path):
    b = SessBroker()
    rows = _session(tmp_path, b, "late_morning")
    assert len(b.spread_orders) == 1
    assert any(r["strategy"] == "O2" for r in rows)
    log = (tmp_path / "log.csv").read_text()
    assert ",O2," in log
    b2 = SessBroker()
    _session(tmp_path / "2", b2, "open")
    assert b2.spread_orders == []


def test_old_state_file_without_options_key_loads(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"peak_equity": 1.0, "day": "2026-11-09",
                             "day_start_equity": 1.0, "killed": False, "ran": [],
                             "stopped": {}}))
    s = load_state(p)
    assert s["options"] == {} and s["killed"] is False


# -- review fixes ---------------------------------------------------------------

def _raise(exc):
    def f(*a, **k):
        raise exc
    return f


def test_5xx_on_submit_keeps_entry_unknown_then_reconciles_by_client_id(tmp_path):
    b = OptBroker(mleg_error=RuntimeError("Alpaca POST /v2/orders failed: HTTP 503 x"),
                  state_path=tmp_path / "s.json")
    state, rows = _run(tmp_path, b)
    sp = state["options"]["spreads"]["2026-11-10:SPY"]
    assert sp["status"] == "unknown" and sp["unknown_of"] == "pending_open"
    saved = load_state(tmp_path / "s.json")["options"]["spreads"]["2026-11-10:SPY"]
    assert saved["status"] == "unknown"
    assert any("unknown" in r["note"] for r in rows) and b.option_orders == []
    coid = "2026-11-10:late_morning:O2:SPY:open"
    b2 = OptBroker(quotes={}, by_client={coid: {
        "id": "real", "status": "filled", "filled_qty": "2", "filled_avg_price": "-1.2"}})
    b2.positions = {occ("SPY", 95): Position(occ("SPY", 95), -2, 0, 0, 0, 0),
                    occ("SPY", 90): Position(occ("SPY", 90), 2, 0, 0, 0, 0)}
    state, rows = _run(tmp_path, b2, state=state, now=NOW + timedelta(days=1))
    sp = state["options"]["spreads"]["2026-11-10:SPY"]
    assert sp["status"] == "open" and sp["order_id"] == "real"
    assert any(r["side"] == "fill" and r["strategy"] == "O2" for r in rows)


def test_unknown_not_found_by_client_id_is_dropped_with_row(tmp_path):
    b = OptBroker(mleg_error=RuntimeError("timeout"))
    state, _ = _run(tmp_path, b)
    assert state["options"]["spreads"]["2026-11-10:SPY"]["status"] == "unknown"
    b2 = OptBroker(quotes={})
    state, rows = _run(tmp_path, b2, state=state, now=NOW + timedelta(days=1))
    assert "2026-11-10:SPY" not in state["options"]["spreads"]
    assert any(r["side"] == "unfilled" for r in rows)


def test_unknown_entry_stays_and_counts_toward_risk_when_lookup_fails(tmp_path):
    state = {"options": {"spreads": {"u": {**_open_spread(), "status": "unknown",
                                           "unknown_of": "pending_open",
                                           "max_loss": 1000.0, "order_id": "",
                                           "client_order_id": "c"}}}}
    b = OptBroker(positions=_legs_pos())
    b.get_order_by_client_id = _raise(OSError("net down"))
    state, _ = _run(tmp_path, b, state=state)
    assert state["options"]["spreads"]["u"]["status"] == "unknown"
    assert b.spread_orders == []                    # spread bucket full


def test_one_leg_missing_marks_broken_buys_back_short_and_blocks_opens(tmp_path):
    state = {"options": {"spreads": {"x": _open_spread()}}}
    s = occ("SPY", 95)
    b = OptBroker(positions={s: Position(s, -1, -200, 2.4, 2.0, 0)})
    state, rows = _run(tmp_path, b, state=state)
    assert state["options"]["spreads"]["x"]["status"] == "broken"
    assert b.option_orders and b.option_orders[0][:5] == (s, 1, "buy", "buy_to_close",
                                                          "limit")
    assert b.option_orders[0][5] == 2.10                    # short ask
    assert b.spread_orders == []                            # no new opens
    assert any("BROKEN" in r["note"] for r in rows)
    assert any("blocked" in r["note"].lower() for r in rows)


def test_both_legs_missing_stays_broken_and_blocks_opens(tmp_path):
    state = {"options": {"spreads": {"x": _open_spread()}}}
    b = OptBroker()
    state, _ = _run(tmp_path, b, state=state)
    assert state["options"]["spreads"]["x"]["status"] == "broken"
    assert b.spread_orders == [] and b.option_orders == []


def test_qty_mismatch_is_broken_and_buys_back_only_naked_part(tmp_path):
    sp = {**_open_spread(), "contracts": 2}
    s, lg = sp["short"], sp["long"]
    b = OptBroker(positions={s: Position(s, -2, 0, 0, 0, 0),
                             lg: Position(lg, 1, 0, 0, 0, 0)})
    state, _ = _run(tmp_path, b, state={"options": {"spreads": {"x": sp}}})
    assert state["options"]["spreads"]["x"]["status"] == "broken"
    assert b.option_orders[0][:4] == (s, 1, "buy", "buy_to_close")


def test_untracked_spy_put_position_blocks_opens(tmp_path):
    stray = occ("SPY", 72)
    b = OptBroker(positions={stray: Position(stray, 2, 300, 1.5, 1.5, 0)})
    _, rows = _run(tmp_path, b)
    assert b.spread_orders == [] and b.option_orders == []
    assert any("out of sync" in r["note"] for r in rows)


def test_untracked_o2_open_order_blocks_opens(tmp_path):
    b = OptBroker(open_orders=[{"id": "q", "symbol": "", "legs": [],
                                "client_order_id": "2026-11-09:late_morning:O2:SPY:open"}])
    _run(tmp_path, b)
    assert b.spread_orders == []


def test_missing_state_file_with_broker_o2_positions_blocks_opens(tmp_path):
    state = load_state(tmp_path / "nope.json")
    b = OptBroker(positions=_legs_pos())
    _, rows = _run(tmp_path, b, state=state)
    assert b.spread_orders == [] and b.option_orders == []
    assert any("out of sync" in r["note"] for r in rows)


def test_reconcile_rows_for_fill_and_unfilled(tmp_path):
    a = {**_open_spread(), "status": "pending_open", "order_id": "f"}
    c = {**_open_spread(und="QQQ"), "status": "pending_open", "order_id": "e"}
    b = OptBroker(quotes={}, positions=_legs_pos(), order_status={
        "f": {"status": "filled", "filled_qty": "1", "filled_avg_price": "-2.4"},
        "e": {"status": "expired", "filled_qty": "0"}})
    state, rows = _run(tmp_path, b, state={"options": {"spreads": {"a": a, "c": c}}})
    assert state["options"]["spreads"]["a"]["status"] == "open"
    assert "c" not in state["options"]["spreads"]
    fill = [r for r in rows if r["side"] == "fill"]
    unf = [r for r in rows if r["side"] == "unfilled"]
    assert fill and fill[0]["strategy"] == "O2" and "credit=2.40" in fill[0]["note"]
    assert unf and "not filled" in unf[0]["note"] and occ("QQQ", 95) in unf[0]["symbol"]


def test_partial_close_reconcile_row_and_remaining_contracts(tmp_path):
    sp = {**_open_spread(), "contracts": 2, "status": "pending_close",
          "close_order_id": "c1"}
    b = OptBroker(quotes={}, order_status={"c1": {
        "status": "expired", "filled_qty": "1", "filled_avg_price": "1.40"}},
        positions={occ("SPY", 95): Position(occ("SPY", 95), -1, 0, 0, 0, 0),
                   occ("SPY", 90): Position(occ("SPY", 90), 1, 0, 0, 0, 0)})
    state, rows = _run(tmp_path, b, state={"options": {"spreads": {"x": sp}}},
                       allowed=False)
    assert state["options"]["spreads"]["x"]["contracts"] == 1
    assert state["options"]["spreads"]["x"]["status"] == "open"
    row = [r for r in rows if r["side"] == "close_fill"][0]
    assert "realised_pnl=100.00" in row["note"] and row["qty"] == 1     # (2.4-1.4)*100


def test_market_closed_and_no_new_rows_use_neutral_tag(tmp_path):
    _, rows = _run(tmp_path, OptBroker(), market_open=False)
    assert rows[0]["strategy"] == "OPT"
    _, rows = _run(tmp_path / "2", OptBroker(), allowed=False)
    assert any(r["strategy"] == "OPT" and "no new options" in r["note"] for r in rows)


def test_hedge_sell_capped_at_held_qty_and_marked_broken(tmp_path):
    exp = TODAY + timedelta(days=10)
    h = occ("SPY", 95, exp)
    state = {"options": {"hedges": {h: {"qty": 3, "cost_basis": 600.0,
                                        "expiry": exp.isoformat(), "status": "open"}}}}
    b = OptBroker(positions={h: Position(h, 2, 100, 2.0, 0.5, 0)},
                  quotes={h: OptionQuote(h, 0.45, 0.55, NOW - timedelta(minutes=1))})
    state, rows = _run(tmp_path, b, state=state)
    assert b.option_orders[0][:4] == (h, 2, "sell", "sell_to_close")
    assert any("BROKEN" in r["note"] for r in rows)
    assert b.spread_orders == []


def test_options_exception_does_not_break_stock_session(tmp_path):
    b = SessBroker()
    b.get_option_positions = _raise(RuntimeError("opt down"))
    rows = _session(tmp_path, b, "late_morning")
    assert b.equity_orders                                  # stocks still traded
    err = [r for r in rows if r["side"] == "error"]
    assert err and err[0]["strategy"] == "OPT"
    assert (tmp_path / "s.json").exists()


def test_stock_exception_does_not_skip_options_closes(tmp_path):
    import pytest
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"peak_equity": 100_000.0, "day": "2026-11-10",
                             "day_start_equity": 100_000.0, "killed": False,
                             "ran": [], "stopped": {},
                             "options": {"spreads": {"x": _open_spread(credit=2.40)}}}))
    b = SessBroker(positions=_legs_pos(), quotes=_close_quotes(1.15, 1.25, 0.0, 0.10))
    b.submit_order = _raise(RuntimeError("stock order failed"))
    with pytest.raises(RuntimeError):
        _session(tmp_path, b, "late_morning")
    assert b.spread_orders and b.spread_orders[0][3].endswith("O2:x:close")
    assert load_state(p)["options"]["spreads"]["x"]["status"] == "pending_close"
