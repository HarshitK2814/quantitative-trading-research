"""Pure options planning: risk cap, spread selection, close rules."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd

from src.broker import OptionContract, OptionQuote, Position
from src.intraday import options as o
from src.intraday.strategies import REGISTRY

NOW = datetime(2026, 11, 10, 16, 30, tzinfo=UTC)
TODAY = date(2026, 11, 10)
EXP = TODAY + timedelta(days=35)


def q(sym, bid, ask, age_min=1):
    return OptionQuote(sym, bid, ask, NOW - timedelta(minutes=age_min))


def put(strike, exp=EXP, und="SPY"):
    sym = f"{und}{exp:%y%m%d}P{int(strike * 1000):08d}"
    return OptionContract(sym, und, "put", float(strike), exp, True)


# -- max loss and risk cap ------------------------------------------------------

def test_spread_max_loss_math():
    assert o.spread_max_loss(5.0, 1.20, 2) == (5.0 - 1.20) * 100 * 2
    assert o.spread_max_loss(5.0, 1.0, 1) == 400.0


def test_risk_used_sums_hedge_cost_and_spread_max_loss():
    opts = {"hedges": {"H": {"cost_basis": 300.0, "status": "open"}},
            "spreads": {"a": {"max_loss": 400.0}, "b": {"max_loss": 380.0}}}
    assert o.risk_used(opts) == (300.0, 780.0)
    assert o.risk_used({}) == (0.0, 0.0)


def test_risk_check_blocks_when_total_at_or_over_2pct():
    opts = {"hedges": {"H": {"cost_basis": 1000.0}},
            "spreads": {"a": {"max_loss": 1000.0}}}
    ok, why = o.risk_check(opts, 100_000.0, "spread", 1.0)
    assert not ok and "2%" in why


def test_risk_check_blocks_new_open_that_would_breach_bucket_or_total():
    opts = {"spreads": {"a": {"max_loss": 700.0}}}
    assert not o.risk_check(opts, 100_000.0, "spread", 400.0)[0]   # 1100 > 1%
    assert o.risk_check(opts, 100_000.0, "spread", 300.0)[0]       # 1000 == 1%
    assert not o.risk_check({}, 100_000.0, "hedge", 1001.0)[0]
    assert o.risk_check({}, 100_000.0, "hedge", 1000.0)[0]
    assert not o.risk_check({}, 0.0, "hedge", 1.0)[0]               # no equity


def test_budget_is_min_of_bucket_and_total_room():
    opts = {"hedges": {"H": {"cost_basis": 900.0}},
            "spreads": {"a": {"max_loss": 500.0}}}
    assert o.budget(opts, 100_000.0, "spread") == 500.0
    assert o.budget(opts, 100_000.0, "hedge") == 100.0


# -- quotes ---------------------------------------------------------------------

def test_quote_ok_rejects_missing_stale_and_bad_quotes():
    assert o.quote_ok(q("X", 1.0, 1.1), NOW)
    assert not o.quote_ok(None, NOW)
    assert not o.quote_ok(q("X", 1.0, 1.1, age_min=30), NOW)
    assert not o.quote_ok(OptionQuote("X", 1.0, 1.1), NOW)       # no timestamp
    assert not o.quote_ok(q("X", 0.0, 0.0), NOW)
    assert not o.quote_ok(q("X", 1.2, 1.1), NOW)                 # crossed


# -- spread selection -----------------------------------------------------------

def _chain(spot=100.0):
    cs = [put(k) for k in (85, 90, 95, 100)]
    quotes = {cs[0].symbol: q(cs[0].symbol, 0.30, 0.40),
              cs[1].symbol: q(cs[1].symbol, 0.80, 0.90),
              cs[2].symbol: q(cs[2].symbol, 2.00, 2.10),
              cs[3].symbol: q(cs[3].symbol, 4.0, 4.2)}
    return cs, quotes


def test_select_spread_picks_short_5pct_otm_and_long_5_lower():
    cs, quotes = _chain()
    plan, why = o.select_spread(cs, quotes, 100.0, TODAY, NOW)
    assert plan is not None, why
    assert (plan.short_strike, plan.long_strike) == (95.0, 90.0)
    assert plan.width == 5.0
    assert plan.credit == round(2.05 - 0.85, 2)  # mid credit 1.20
    assert plan.max_loss_per_contract == (5.0 - 1.20) * 100


def test_select_spread_requires_credit_at_least_20pct_of_width():
    cs, quotes = _chain()
    quotes[cs[2].symbol] = q(cs[2].symbol, 1.50, 1.60)   # credit 0.70 < 1.00
    plan, why = o.select_spread(cs, quotes, 100.0, TODAY, NOW)
    assert plan is None and "credit" in why


def test_select_spread_needs_both_legs_and_fresh_quotes():
    cs, quotes = _chain()
    no_long = [c for c in cs if c.strike_price != 90]
    assert o.select_spread(no_long, quotes, 100.0, TODAY, NOW)[0] is None
    stale = dict(quotes)
    stale[cs[1].symbol] = q(cs[1].symbol, 0.8, 0.9, age_min=60)
    plan, why = o.select_spread(cs, stale, 100.0, TODAY, NOW)
    assert plan is None and "quote" in why
    missing = {k: v for k, v in quotes.items() if k != cs[2].symbol}
    assert o.select_spread(cs, missing, 100.0, TODAY, NOW)[0] is None


def test_select_spread_uses_nearest_short_strike_that_has_a_5_lower_leg():
    cs = [put(k) for k in (90, 95, 96)]       # target 95.62; 96 nearest, 91 missing
    quotes = {c.symbol: q(c.symbol, 2.0, 2.1) for c in cs}
    quotes[cs[0].symbol] = q(cs[0].symbol, 0.7, 0.8)
    plan, why = o.select_spread(cs, quotes, 100.65, TODAY, NOW)
    assert plan is not None, why
    assert (plan.short_strike, plan.long_strike) == (95.0, 90.0)


def test_select_spread_refuses_short_strike_outside_4_to_6pct_otm():
    cs = [put(k) for k in (95, 100)]          # only pair is 100/95: 0% OTM
    quotes = {c.symbol: q(c.symbol, 2.0, 2.1) for c in cs}
    assert o.select_spread(cs, quotes, 100.0, TODAY, NOW)[0] is None


def test_select_spread_only_uses_30_to_45_dte():
    near = [put(k, TODAY + timedelta(days=20)) for k in (90, 95)]
    far = [put(k, TODAY + timedelta(days=60)) for k in (90, 95)]
    quotes = {c.symbol: q(c.symbol, 2.0, 2.1) for c in near + far}
    assert o.select_spread(near + far, quotes, 100.0, TODAY, NOW)[0] is None


def test_size_spread_rounds_down_to_budget():
    assert o.size_contracts(380.0, 1000.0) == 2
    assert o.size_contracts(380.0, 300.0) == 0
    assert o.size_contracts(0.0, 1000.0) == 0


def test_spread_legs_always_two_and_never_naked():
    cs, quotes = _chain()
    plan, _ = o.select_spread(cs, quotes, 100.0, TODAY, NOW)
    legs = o.spread_legs(plan.short_symbol, plan.long_symbol, opening=True)
    assert [(lg["side"], lg["position_intent"]) for lg in legs] == [
        ("sell", "sell_to_open"), ("buy", "buy_to_open")]
    legs = o.spread_legs(plan.short_symbol, plan.long_symbol, opening=False)
    assert [(lg["side"], lg["position_intent"]) for lg in legs] == [
        ("buy", "buy_to_close"), ("sell", "sell_to_close")]


# -- open gate ------------------------------------------------------------------

def test_spread_open_requires_trend_long_news_ok_and_under_two_open():
    assert o.spread_open_allowed(True, "ok", 0)[0]
    assert o.spread_open_allowed(True, "ok", 1)[0]
    assert not o.spread_open_allowed(True, "ok", 2)[0]
    assert not o.spread_open_allowed(False, "ok", 0)[0]
    assert not o.spread_open_allowed(True, "reduce", 0)[0]
    assert not o.spread_open_allowed(True, "veto", 0)[0]
    assert not o.spread_open_allowed(True, None, 0)[0]


def test_trend_long_uses_s1_rule_and_stale_data_means_not_long():
    up = pd.Series(np.linspace(100, 300, 300),
                   index=pd.date_range(end="2026-11-09", periods=300))
    spec = REGISTRY["S1"]
    assert o.trend_long(spec, up, TODAY) is True
    assert o.trend_long(spec, up[::-1].set_axis(up.index), TODAY) is False
    assert o.trend_long(spec, up, TODAY + timedelta(days=10)) is False
    assert o.trend_long(spec, None, TODAY) is False


# -- close rules ----------------------------------------------------------------

def _spread(credit=1.20, exp=EXP):
    return {"short": "S", "long": "L", "credit": credit, "width": 5.0,
            "contracts": 1, "expiry": exp.isoformat(), "status": "open"}


def test_close_at_50pct_profit():
    reason, _ = o.close_reason(_spread(), q("S", 0.80, 0.90), q("L", 0.25, 0.35),
                               TODAY, NOW)
    assert reason == "profit"   # value 0.85-0.30=0.55 <= 0.60


def test_close_at_7_dte_even_without_quotes():
    sp = _spread(exp=TODAY + timedelta(days=7))
    assert o.close_reason(sp, None, None, TODAY, NOW)[0] == "dte"


def test_close_at_2x_credit_stop():
    reason, _ = o.close_reason(_spread(), q("S", 3.30, 3.40), q("L", 0.90, 0.95),
                               TODAY, NOW)
    assert reason == "stop"     # value 3.35-0.925=2.425 >= 2.40


def test_hold_inside_band_or_on_stale_quotes():
    assert o.close_reason(_spread(), q("S", 1.9, 2.0), q("L", 0.75, 0.85),
                          TODAY, NOW)[0] is None
    assert o.close_reason(_spread(), q("S", 0.1, 0.2, age_min=60), q("L", 0, 0.05),
                          TODAY, NOW)[0] is None


def test_close_debit_uses_natural_price_capped_at_width():
    assert o.close_debit(q("S", 0.80, 0.90), q("L", 0.25, 0.35), 5.0) == 0.65
    assert o.close_debit(q("S", 6.0, 6.5), q("L", 0.5, 0.6), 5.0) == 5.0


# -- hedge cap ------------------------------------------------------------------

def test_hedge_contracts_cut_to_premium_budget():
    assert o.hedge_contracts(3, 400.0, 1000.0) == 2
    assert o.hedge_contracts(1, 400.0, 1000.0) == 1
    assert o.hedge_contracts(3, 1200.0, 1000.0) == 0
    assert o.hedge_contracts(3, 0.0, 1000.0) == 0       # no price, no trade


# -- reconcile and leg checks ---------------------------------------------------

def test_reconcile_pending_open():
    e = {"status": "pending_open", "contracts": 2, "credit": 1.2, "width": 5.0,
         "max_loss": 760.0}
    filled = o.reconcile_spread(e, {"status": "filled", "filled_qty": "2",
                                    "filled_avg_price": "-1.25"})
    assert filled["status"] == "open" and filled["credit"] == 1.25
    assert filled["max_loss"] == o.spread_max_loss(5.0, 1.25, 2)
    assert o.reconcile_spread(e, {"status": "expired", "filled_qty": "0"}) is None
    part = o.reconcile_spread(e, {"status": "canceled", "filled_qty": "1"})
    assert part["status"] == "open" and part["contracts"] == 1
    assert o.reconcile_spread(e, {"status": "new"}) == e
    assert o.reconcile_spread(e, None) == e


def test_reconcile_pending_close():
    e = {"status": "pending_close", "contracts": 2, "credit": 1.2, "width": 5.0,
         "max_loss": 760.0}
    assert o.reconcile_spread(e, {"status": "filled", "filled_qty": "2"}) is None
    back = o.reconcile_spread(e, {"status": "expired", "filled_qty": "0"})
    assert back["status"] == "open"


def test_reconcile_hedge_sets_real_cost_basis():
    e = {"status": "pending_open", "qty": 1, "cost_basis": 500.0}
    out = o.reconcile_hedge(e, {"status": "filled", "filled_qty": "1",
                                "filled_avg_price": "4.10"})
    assert out["status"] == "open" and out["cost_basis"] == 410.0


def test_legs_held_checks_both_signs():
    sp = {"short": "S", "long": "L", "contracts": 1}
    pos = {"S": Position("S", -1, -100, 1, 1, 0), "L": Position("L", 1, 50, 1, 1, 0)}
    assert o.legs_held(sp, pos)
    assert not o.legs_held(sp, {"S": pos["S"]})
    assert not o.legs_held(sp, {"S": pos["L"], "L": pos["L"]})
