"""Options step of the late_morning session: O1 hedge and O2 put credit spread.

Order of work: reconcile earlier orders (with log rows) -> scan the broker for
untracked O1/O2-like positions/orders -> closes and repairs (always allowed)
-> new opens. New opens are blocked by the kill switch, daily-loss halt,
stale state, the 2% risk cap, any broken entry, or any untracked
(orphan) position/order. State is saved before every order. Only option
symbols recorded in state["options"] are ever closed.
"""

from __future__ import annotations

import dataclasses
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
NEUTRAL = "OPT"     # tag for rows that are about the options step, not O1/O2
_MAX_QUOTES = 100   # Alpaca latest-quotes symbol limit per request
_PENDING = ("pending_open", "pending_close")


def _lookup(broker, entry: dict) -> dict | None:
    """Order for an entry's pending/unknown order. 404 reads as "rejected".

    Returns None when the lookup itself failed (try again next run).
    """
    stage = entry.get("unknown_of") if entry.get("status") == "unknown" else entry.get("status")
    closing = stage == "pending_close"
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


def _label(kind: str, eid: str, e: dict) -> str:
    return f"{e['short']}/{e['long']}" if kind == "spread" else eid


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
        emit("OPTIONS", "skip", 0, 0.0, note="market closed", strategy=NEUTRAL)
        return
    today = now_utc.astimezone(ET).date()
    failures: list[str] = []

    def place(book: dict, eid: str, entry: dict, id_key: str, submit) -> str | None:
        """Save state, then submit. Order id, "" on dry run, None if not confirmed.

        HTTP 4xx (or local validation) = not placed: entry restored/removed.
        5xx / network / anything else = outcome unknown: a pending entry is kept
        with status "unknown" (still counted as risk) and is matched by its
        client_order_id on the next run.
        """
        prev = book.get(eid)
        book[eid] = {**entry, id_key: ""}
        if dry_run:
            return ""
        save_state(state_path, state)
        try:
            res = submit()
        except Exception as exc:  # noqa: BLE001 - classified below
            if o.classify_submit_error(exc) == "rejected":
                if prev is None:
                    del book[eid]
                else:
                    book[eid] = prev
                failures.append(f"rejected: {str(exc)[:150]}")
            else:
                e = book[eid]
                if e["status"] in _PENDING:
                    e["unknown_of"], e["status"] = e["status"], "unknown"
                failures.append(f"outcome unknown, kept as unknown: {str(exc)[:120]}")
                logger.warning("order outcome unknown: %s", exc)
            save_state(state_path, state)
            return None
        book[eid][id_key] = res.order_id
        save_state(state_path, state)
        return res.order_id

    # 1. reconcile earlier orders, logging what changed
    for book, kind, fn, tag in ((spreads, "spread", o.reconcile_spread, "O2"),
                                (hedges, "hedge", o.reconcile_hedge, "O1")):
        for eid, e in list(book.items()):
            st = e.get("status")
            if st not in (*_PENDING, "unknown"):
                continue
            order = _lookup(broker, e)
            if st == "unknown":
                if order is None:
                    emit(_label(kind, eid, e), "skip", 0, 0.0, strategy=tag,
                         note="order outcome still unknown; counted as risk")
                    continue
                before = {k: v for k, v in e.items() if k != "unknown_of"}
                before["status"] = e["unknown_of"]
                new = o.resolve_unknown(e, order, fn)
            else:
                before, new = e, fn(e, order)
            ev = o.describe_reconcile(kind, before, new, order)
            if new is None:
                del book[eid]
            else:
                book[eid] = new
            if ev:
                emit(_label(kind, eid, e), ev["side"], ev["qty"], ev["price"],
                     note=ev["note"], order_id=(order or {}).get("id", ""), strategy=tag)

    positions = broker.get_option_positions()
    orphans = o.find_orphans(opts, positions, broker.get_orders(status="open", nested=True))

    # 2. closes and repairs: always allowed
    for sid, sp in list(spreads.items()):
        if sp["status"] not in ("open", "broken"):
            continue
        if o.legs_held(sp, positions):
            if sp["status"] == "broken":
                spreads[sid] = sp = {**sp, "status": "open"}
                emit(_label("spread", sid, sp), "skip", 0, 0.0, strategy="O2",
                     note=f"spread {sid} legs match again; broken flag cleared")
        else:
            if sp["status"] != "broken":
                spreads[sid] = sp = {**sp, "status": "broken"}
                if not dry_run:
                    save_state(state_path, state)
            s_pos, l_pos = positions.get(sp["short"]), positions.get(sp["long"])
            emit(_label("spread", sid, sp), "skip", 0, 0.0, strategy="O2",
                 note=(f"BROKEN spread {sid}: held short={s_pos.qty if s_pos else 0} "
                       f"long={l_pos.qty if l_pos else 0} expected "
                       f"-{sp['contracts']}/+{sp['contracts']}; new opens blocked"))
            naked = o.naked_short_qty(sp, positions)
            if naked > 0:
                q = broker.get_option_quotes([sp["short"]]).get(sp["short"])
                if not o.quote_ok(q, now_utc):
                    emit(sp["short"], "skip", 0, 0.0, strategy="O2",
                         note="BROKEN: naked short needs buy-back but no fresh quote")
                    continue
                coid = f"{key}:O2:{sid}:repair"
                entry = {**sp, "repair_client_order_id": coid}
                oid = place(spreads, sid, entry, "repair_order_id",
                            lambda: broker.submit_option_order(
                                sp["short"], naked, "buy", "buy_to_close", "limit",
                                q.ask, "day", coid))
                emit(sp["short"], "buy", naked, q.ask, order_id=oid or "", strategy="O2",
                     note=("BROKEN: buy back naked short leg" if oid is not None
                           else f"BROKEN: buy-back not confirmed: {failures[-1]}"))
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
        qty = min(int(sp["contracts"]), int(round(-positions[sp["short"]].qty)),
                  int(round(positions[sp["long"]].qty)))
        debit = o.close_debit(sq, lq, sp["width"])
        coid = f"{key}:O2:{sid}:close"
        entry = {**sp, "status": "pending_close", "close_client_order_id": coid}
        legs = o.spread_legs(sp["short"], sp["long"], opening=False)
        oid = place(spreads, sid, entry, "close_order_id",
                    lambda: broker.submit_spread_order(legs, qty, debit,
                                                       client_order_id=coid))
        note = (f"close {reason} value={value:.2f} credit={sp['credit']:.2f} "
                f"debit_limit={debit:.2f} legs=buy {sp['short']} sell {sp['long']}")
        if oid is None:
            note = f"close {reason} not confirmed: {failures[-1]}"
        emit(_label("spread", sid, sp), "buy_spread", qty, debit,
             note=note, order_id=oid or "", strategy="O2")

    for hid, h in list(hedges.items()):
        if h["status"] not in ("open", "broken"):
            continue
        pos = positions.get(hid)
        held = int(round(pos.qty)) if pos and pos.qty > 0 else 0
        if held != int(h["qty"]):
            if h["status"] != "broken":
                hedges[hid] = h = {**h, "status": "broken"}
            emit(hid, "skip", 0, 0.0, strategy="O1",
                 note=f"BROKEN hedge: held {held}, expected {h['qty']}; new opens blocked")
        elif h["status"] == "broken":
            hedges[hid] = h = {**h, "status": "open"}
        if held <= 0 or not needs_roll(date.fromisoformat(h["expiry"]), today):
            continue
        q = broker.get_option_quotes([hid]).get(hid)
        if not o.quote_ok(q, now_utc) or q.bid <= 0:
            emit(hid, "skip", 0, 0.0, strategy="O1", note="roll due but no fresh bid")
            continue
        qty = min(int(h["qty"]), held)
        coid = f"{key}:O1:{hid}:close"
        entry = {**h, "status": "pending_close", "close_client_order_id": coid}
        if h["status"] == "broken":   # keep it flagged; still sell what is held
            entry = {**h, "close_client_order_id": coid}
        oid = place(hedges, hid, entry, "close_order_id",
                    lambda: broker.submit_option_order(
                        hid, qty, "sell", "sell_to_close", "limit", q.bid, "day", coid))
        emit(hid, "sell", qty, q.bid, order_id=oid or "", strategy="O1",
             note="hedge roll close (<14 DTE)" if oid is not None
             else f"hedge close not confirmed: {failures[-1]}")

    # 3. new opens
    broken = [eid for book in (spreads, hedges) for eid, e in book.items()
              if e["status"] == "broken"]
    if not allowed:
        emit("OPTIONS", "skip", 0, 0.0, note=f"no new options: {why}", strategy=NEUTRAL)
        return
    if broken:
        emit("OPTIONS", "skip", 0, 0.0, strategy=NEUTRAL,
             note=f"no new options: BLOCKED by broken entries {broken}")
        return
    if orphans:
        emit("OPTIONS", "skip", 0, 0.0, strategy=NEUTRAL,
             note=f"no new options: state may be out of sync, untracked {orphans[:5]}")
        return
    _open_hedge(broker, opts, equity, prices, today, now_utc, key, registry,
                equity_positions, place, emit, failures)
    _open_spreads(broker, opts, equity, closes, registry, gate, prices, today,
                  now_utc, key, place, emit, failures)


def _open_hedge(broker, opts, equity, prices, today, now_utc, key, registry,
                equity_positions, place, emit, failures) -> None:
    hedges = opts["hedges"]
    if any(h["status"] != "pending_close" for h in hedges.values()):
        return  # already hedged (or an order pending/unknown)
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
    oid = place(hedges, c.symbol, entry, "order_id", lambda: broker.submit_option_order(
        c.symbol, n, "buy", "buy_to_open", "limit", limit, "day", coid))
    note = (f"hedge open debit={limit:.2f} cost<={premium * n:.0f} "
            f"covers={plan.notional_covered:.0f} of {exposure:.0f}")
    if oid is None:
        note = f"hedge open not confirmed: {failures[-1]}"
    emit(c.symbol, "buy", n, limit, note=note, order_id=oid or "", strategy="O1")


def _open_spreads(broker, opts, equity, closes, registry, gate, prices, today,
                  now_utc, key, place, emit, failures) -> None:
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
        oid = place(spreads, sid, entry, "order_id", lambda: broker.submit_spread_order(
            legs, n, -plan.credit, client_order_id=coid))
        note = (f"open credit={plan.credit:.2f} width={plan.width:g} "
                f"max_loss={max_loss:.0f} exp={plan.expiry} "
                f"legs=sell {plan.short_symbol} buy {plan.long_symbol}")
        if oid is None:
            note = f"mleg order not confirmed, no single-leg fallback: {failures[-1]}"
        emit(f"{plan.short_symbol}/{plan.long_symbol}", "sell_spread", n, plan.credit,
             verdict, note, order_id=oid or "", strategy="O2")
