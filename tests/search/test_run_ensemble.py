from types import SimpleNamespace as P

from scripts.run_ensemble import plan_orders


def pos(sym, qty, px):
    return P(symbol=sym, qty=qty, current_price=px, market_value=qty * px)


def test_stale_symbol_is_held():
    o = plan_orders({"AAA": 0.1}, {}, {"AAA": 10.0}, 10_000, {"AAA"})
    assert o == []


def test_buy_and_full_exit_uses_held_qty():
    positions = {"BBB": pos("BBB", 7, 10.0)}
    o = plan_orders({"AAA": 0.1}, positions, {"AAA": 10.0, "BBB": 10.0}, 10_000,
                    set(), owned={"AAA", "BBB"})
    assert (1, "AAA", "buy", 100, 10.0) in o
    assert (0, "BBB", "sell", 7, 10.0) in o


def test_option_symbols_never_traded():
    occ = "SPY261218P00500000"
    positions = {occ: pos(occ, 2, 5.0)}
    assert plan_orders({}, positions, {occ: 5.0}, 10_000, set(), owned={occ}) == []
