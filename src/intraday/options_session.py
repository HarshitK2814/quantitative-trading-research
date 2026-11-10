"""Options step of the late_morning session: O1 hedge and O2 put credit spread.

Order of work: reconcile pending orders -> closes (always allowed) -> new
opens (only when buys are allowed and the 2% options risk cap has room).
State is saved before every order. Only option symbols recorded in
state["options"] are ever closed; nothing else in the account is touched.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

from src.hedge import expiry_window, needs_roll, plan_hedge
from src.intraday import options as o
from src.intraday.limits import save_state
from src.intraday.schedule import ET

logger = logging.getLogger(__name__)

SESSION = "late_morning"
_MAX_QUOTES = 100  # Alpaca latest-quotes symbol limit per request


def _lookup(broker, entry: dict) -> dict | None:
    """Order dict for an entry's pending order; a missing order reads as rejected."""
    closing = entry.get("status") == "pending_close"
    oid = entry.get("close_order_id" if closing else "order_id")
    coid = entry.get("close_client_order_id" if closing else "client_order_id")
    try:
        if oid:
            return broker.get_order(oid)
        if coid:
            return broker.get_order_by_client_id(coid)
    except RuntimeError as exc:
        if "HTTP 404" in str(exc):
            return {"status": "rejected", "filled_qty": "0"}
        logger.warning("order lookup failed: %s", exc)
    except Exception as exc:  # noqa: BLE001 - network; retry next run
        logger.warning("order lookup failed: %s", exc)
    return None


def run_options(
    *, key: str, session: str, broker, state: dict, equity: float, closes: dict,
    registry: dict, gate: Callable, prices: dict[str, float], now_utc: datetime,
    allowed: bool, why: str, market_open: bool, dry_run: bool, state_path: Path,
    equity_positions: dict, emit: Callable,
) -> None:
    """Run the options sleeve once. `emit` logs one row (session's log fn)."""
    if session != SESSION:
        return
    opts = state.setdefault("options", {})
    hedges = opts.setdefault("hedges", {})
    spreads = opts.setdefault("spreads", {})
    if not market_open:
        emit("OPTIONS", "skip", 0, 0.0, note="market closed", strategy="O2")
        return
    today = now_utc.astimezone(ET).date()

    def place(book: dict, eid: str, entry: dict, closing: bool, submit) -> str | None:
        """Save state, then submit. Returns order id, "" on dry run, None on failure."""
        prev = book.get(eid)
        id_key = "close_order_id" if closing else "order_id"
        book[eid] = {**entry, id_key: ""}
        if dry_run:
            return ""
        save_state(state_path, state)
        try:
            res = submit()
        except RuntimeError as exc:   # API answered with an error: nothing placed
            if prev is None:
                del book[eid]
            else:
                book[eid] = prev
            save_state(state_path, state)
            return _fail(exc)
        except Exception as exc:  # noqa: BLE001 - unknown outcome; reconcile by client id
            save_state(state_path, state)
            logger.warning("order outcome unknown, will reconcile: %s", exc)
            failures.append(f"outcome unknown, kept pending: {str(exc)[:120]}")
            return None
        book[eid][id_key] = res.order_id
        save_state(state_path, state)
        return res.order_id

    failures: list[str] = []

    def _fail(exc) -> None:
        failures.append(str(exc)[:160])
        return None

    # 1. reconcile pending orders from earlier runs
    for book, fn in ((spreads, o.reconcile_spread), (hedges, o.reconcile_hedge)):
        for eid, e in list(book.items()):
            if e.get("status") not in ("pending_open", "pending_close"):
                continue
            new = fn(e, _lookup(broker, e))
            if new is None:
                del book[eid]
            else:
                book[eid] = new

    positions = broker.get_option_positions()

    # 2. closes: always allowed
    for sid, sp in list(spreads.items()):
        if sp["status"] != "open":
            continue
        if not o.legs_held(sp, positions):
            del spreads[sid]
            emit(sp["short"], "skip", 0, 0.0, strategy="O2",
                 note=f"spread {sid} legs not held; dropped from state")
            continue
        quotes = broker.get_option_quotes([sp["short"], sp["long"]])
        sq, lq = quotes.get(sp["short"]), quotes.get(sp["long"])
        reason, value = o.close_reason(sp, sq, lq, today, now_utc)
        if reason is None:
            continue
        if not (o.quote_ok(sq, now_utc) and o.quote_ok(lq, now_utc)):
            emit(sp["short"], "skip", 0, 0.0, strategy="O2",
                 note=f"close due ({reason}) but no fresh quote")
            continue
        debit = o.close_debit(sq, lq, sp["width"])
        coid = f"{key}:O2:{sid}:close"
        entry = {**sp, "status": "pending_close", "close_client_order_id": coid}
        legs = o.spread_legs(sp["short"], sp["long"], opening=False)
        oid = place(spreads, sid, entry, True, lambda: broker.submit_spread_order(
            legs, sp["contracts"], debit, client_order_id=coid))
        note = (f"close {reason} value={value:.2f} credit={sp['credit']:.2f} "
                f"debit_limit={debit:.2f} legs=buy {sp['short']} sell {sp['long']}")
        if oid is None:
            note = f"close {reason} rejected/failed: {failures[-1] if failures else ''}"
        emit(f"{sp['short']}/{sp['long']}", "buy_spread", sp["contracts"], debit,
             note=note, order_id=oid or "", strategy="O2")

    for hid, h in list(hedges.items()):
        if h["status"] != "open":
            continue
        pos = positions.get(hid)
        if not pos or pos.qty <= 0:
            del hedges[hid]
            emit(hid, "skip", 0, 0.0, strategy="O1", note="hedge not held; dropped")
            continue
        if not needs_roll(date.fromisoformat(h["expiry"]), today):
            continue
        q = broker.get_option_quotes([hid]).get(hid)
        if not o.quote_ok(q, now_utc) or q.bid <= 0:
            emit(hid, "skip", 0, 0.0, strategy="O1", note="roll due but no fresh bid")
            continue
        coid = f"{key}:O1:{hid}:close"
        entry = {**h, "status": "pending_close", "close_client_order_id": coid}
        oid = place(hedges, hid, entry, True, lambda: broker.submit_option_order(
            hid, int(h["qty"]), "sell", "sell_to_close", "limit", q.bid, "day", coid))
        emit(hid, "sell", h["qty"], q.bid, order_id=oid or "", strategy="O1",
             note="hedge roll close (<14 DTE)" if oid is not None
             else f"hedge close failed: {failures[-1] if failures else ''}")

    # 3. new opens
    if not allowed:
        emit("OPTIONS", "skip", 0, 0.0, note=f"no new options: {why}", strategy="O2")
        return
    _open_hedge(broker, opts, equity, prices, today, now_utc, key, registry,
                equity_positions, place, emit, failures)
    _open_spreads(broker, opts, equity, closes, registry, gate, prices, today,
                  now_utc, key, place, emit, failures)


def _open_hedge(broker, opts, equity, prices, today, now_utc, key, registry,
                equity_positions, place, emit, failures) -> None:
    hedges = opts["hedges"]
    if any(h["status"] != "pending_close" for h in hedges.values()):
        return  # already hedged (or an open order pending)
    syms = {s for spec in registry.values() if spec.active
            and spec.asset_class != "crypto" for s in spec.symbols}
    exposure = sum(p.market_value for s, p in equity_positions.items() if s in syms)
    if exposure <= 0:
        return
    und = o.HEDGE_UNDERLYING
    spot = prices.get(und)
    if not spot:
        emit(und, "skip", 0, 0.0, strategy="O1", note="hedge: no SPY price")
        return
    ok, why = o.risk_check(opts, equity, "hedge", 0.0)
    if not ok:
        emit(und, "skip", 0, 0.0, strategy="O1", note=f"hedge: {why}")
        return
    lo, hi = expiry_window(today)
    contracts = broker.get_option_contracts(und, "put", lo, hi,
                                            strike_gte=round(spot * 0.85, 2),
                                            strike_lte=round(spot, 2), limit=500)
    target = spot * 0.95
    contracts = sorted(contracts, key=lambda c: abs(c.strike_price - target))[:_MAX_QUOTES]
    quotes = broker.get_option_quotes([c.symbol for c in contracts])
    fresh = {k: v for k, v in quotes.items() if o.quote_ok(v, now_utc)}
    plan = plan_hedge(contracts, fresh, spot, exposure)
    if plan is None:
        emit(und, "skip", 0, 0.0, strategy="O1",
             note=f"hedge: no contract or exposure {exposure:.0f} < one contract")
        return
    c = plan.contract
    if c.symbol not in fresh:
        emit(c.symbol, "skip", 0, 0.0, strategy="O1", note="hedge: missing or stale quote")
        return
    limit = round(fresh[c.symbol].mid * 1.05, 2)
    premium = limit * 100.0
    n = o.hedge_contracts(plan.contracts_to_buy, premium, o.budget(opts, equity, "hedge"))
    if n <= 0:
        emit(c.symbol, "skip", 0, limit, strategy="O1",
             note=f"hedge: premium {premium:.0f}/contract over 1% budget")
        return
    ok, why = o.risk_check(opts, equity, "hedge", premium * n)
    if not ok:
        emit(c.symbol, "skip", 0, limit, strategy="O1", note=f"hedge: {why}")
        return
    coid = f"{key}:O1:{c.symbol}:open"
    entry = {"underlying": und, "qty": n, "cost_basis": round(premium * n, 2),
             "strike": c.strike_price, "expiry": c.expiration_date.isoformat(),
             "opened": today.isoformat(), "status": "pending_open",
             "client_order_id": coid}
    oid = place(hedges, c.symbol, entry, False, lambda: broker.submit_option_order(
        c.symbol, n, "buy", "buy_to_open", "limit", limit, "day", coid))
    note = (f"hedge open debit={limit:.2f} cost<={premium * n:.0f} "
            f"covers={plan.notional_covered:.0f} of {exposure:.0f}")
    if oid is None:
        note = f"hedge open rejected/failed: {failures[-1] if failures else ''}"
    emit(c.symbol, "buy", n, limit, note=note, order_id=oid or "", strategy="O1")


def _open_spreads(broker, opts, equity, closes, registry, gate, prices, today,
                  now_utc, key, place, emit, failures) -> None:
    import dataclasses

    spreads = opts["spreads"]
    s1 = registry.get("S1")
    for und in o.SPREAD_UNDERLYINGS:
        spec = dataclasses.replace(s1, symbols=(und,)) if s1 else None
        trend = bool(spec) and o.trend_long(spec, closes.get(und), today)
        ok, why = o.spread_open_allowed(trend, "ok", len(spreads))
        if not ok:
            emit(und, "skip", 0, 0.0, strategy="O2", note=f"spread: {why}")
            continue
        verdict = gate(und)
        ok, why = o.spread_open_allowed(trend, verdict.action, len(spreads))
        if not ok:
            emit(und, "skip", 0, 0.0, verdict, f"spread: {why}", strategy="O2")
            continue
        sid = f"{today.isoformat()}:{und}"
        if sid in spreads:
            continue
        spot = prices.get(und)
        if not spot:
            emit(und, "skip", 0, 0.0, verdict, "spread: no spot price", strategy="O2")
            continue
        ok, why = o.risk_check(opts, equity, "spread", 0.0)
        if not ok:
            emit(und, "skip", 0, 0.0, verdict, f"spread: {why}", strategy="O2")
            continue
        target = spot * (1 - o.SHORT_OTM)
        contracts = broker.get_option_contracts(
            und, "put", today + timedelta(days=o.SPREAD_MIN_DTE),
            today + timedelta(days=o.SPREAD_MAX_DTE),
            strike_gte=round(target - o.SPREAD_WIDTH - 10, 2),
            strike_lte=round(target + 10, 2), limit=1000)
        if contracts:
            first = min(c.expiration_date for c in contracts)
            contracts = [c for c in contracts if c.expiration_date == first]
        contracts = sorted(contracts, key=lambda c: abs(c.strike_price - target))
        quotes = broker.get_option_quotes([c.symbol for c in contracts][:_MAX_QUOTES])
        plan, why = o.select_spread(contracts, quotes, spot, today, now_utc)
        if plan is None:
            emit(und, "skip", 0, 0.0, verdict, f"spread: {why}", strategy="O2")
            continue
        n = o.size_contracts(plan.max_loss_per_contract, o.budget(opts, equity, "spread"))
        if n <= 0:
            emit(und, "skip", 0, plan.credit, verdict, strategy="O2",
                 note=f"spread: max loss {plan.max_loss_per_contract:.0f} over 1% budget")
            continue
        max_loss = o.spread_max_loss(plan.width, plan.credit, n)
        ok, why = o.risk_check(opts, equity, "spread", max_loss)
        if not ok:
            emit(und, "skip", 0, plan.credit, verdict, f"spread: {why}", strategy="O2")
            continue
        coid = f"{key}:O2:{und}:open"
        entry = {"underlying": und, "short": plan.short_symbol, "long": plan.long_symbol,
                 "short_strike": plan.short_strike, "long_strike": plan.long_strike,
                 "width": plan.width, "credit": plan.credit, "contracts": n,
                 "expiry": plan.expiry.isoformat(), "max_loss": max_loss,
                 "opened": today.isoformat(), "status": "pending_open",
                 "client_order_id": coid}
        legs = o.spread_legs(plan.short_symbol, plan.long_symbol, opening=True)
        oid = place(spreads, sid, entry, False, lambda: broker.submit_spread_order(
            legs, n, -plan.credit, client_order_id=coid))
        note = (f"open credit={plan.credit:.2f} width={plan.width:g} "
                f"max_loss={max_loss:.0f} exp={plan.expiry} "
                f"legs=sell {plan.short_symbol} buy {plan.long_symbol}")
        if oid is None:
            note = (f"mleg rejected/failed, skipped (no single-leg fallback): "
                    f"{failures[-1] if failures else 'unknown outcome'}")
        emit(f"{plan.short_symbol}/{plan.long_symbol}", "sell_spread", n, plan.credit,
             verdict, note, order_id=oid or "", strategy="O2")
