"""Run one trading session: signals -> caps -> news gate -> orders -> log."""

from __future__ import annotations

import copy
import csv
import logging
from datetime import datetime
from pathlib import Path

from src.config import RISK
from src.intraday.limits import (
    SessionLimits,
    buys_allowed,
    cap_weights,
    load_state,
    save_state,
    update_state,
)
from src.intraday.schedule import ET
from src.intraday.strategies import completed_bars, target_weights

logger = logging.getLogger(__name__)

LOG_FIELDS = ["ts", "session", "symbol", "strategy", "side", "qty", "price",
              "news_action", "news_reason", "note", "dry_run", "order_id"]


def _norm(sym: str) -> str:
    return sym.replace("/", "")


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def run_session(
    *, name, broker, closes, now_utc: datetime, limits: SessionLimits,
    state_path: Path, log_path: Path, registry, gate, prices: dict[str, float],
    dry_run: bool,
) -> list[dict]:
    """Run one session and return the log rows. Only registry symbols are touched."""
    today_et = now_utc.astimezone(ET).date()
    acct = broker.get_account()
    state = update_state(copy.deepcopy(load_state(state_path)), acct.equity,
                         today_et.isoformat(), limits)
    key = f"{today_et.isoformat()}:{name}"
    if key in state["ran"]:
        if not dry_run:
            save_state(state_path, state)
        return []
    if not dry_run:
        state["ran"].append(key)

    closes = {s: completed_bars(c, today_et) for s, c in closes.items()}
    owner = {s: spec.id for spec in registry.values() if spec.active for s in spec.symbols}
    classes = {s: spec.asset_class for spec in registry.values() if spec.active
               for s in spec.symbols}
    raw = target_weights(registry, closes)
    stopped = state.setdefault("stopped", {})
    for sym in [s for s in stopped if raw.get(s, 0.0) == 0.0]:
        del stopped[sym]
    weights = cap_weights(raw, classes, limits)

    positions = {_norm(s): p for s, p in broker.get_positions().items()}
    notes: dict[str, str] = {}
    for sym in weights:
        pos = positions.get(_norm(sym))
        if pos and pos.avg_entry_price > 0 and \
                pos.current_price <= pos.avg_entry_price * (1 - RISK.stop_loss_pct):
            weights[sym] = 0.0
            notes[sym] = "stop-loss"
            stopped[sym] = today_et.isoformat()

    allowed, why = buys_allowed(state, acct.equity, limits)
    market_open = broker.is_market_open()
    rows: list[dict] = []

    def log(sym, side, qty, price, verdict=None, note="", order_id=""):
        row = {"ts": now_utc.isoformat(), "session": name, "symbol": sym,
               "strategy": owner[sym], "side": side, "qty": qty, "price": price,
               "news_action": getattr(verdict, "action", ""),
               "news_reason": getattr(verdict, "reason", ""),
               "note": note, "dry_run": dry_run, "order_id": order_id}
        if not dry_run:
            _append(log_path, row)
        rows.append(row)

    if not dry_run:
        save_state(state_path, state)  # session key persisted before any order

    for sym, w in weights.items():
        is_crypto = classes[sym] == "crypto"
        if not is_crypto and not market_open:
            continue
        price = prices.get(sym)
        if not price:
            continue
        if sym in stopped and w > 0:
            log(sym, "skip", 0, price, note="stopped out, waiting for signal reset")
            continue
        pos = positions.get(_norm(sym))
        held_val = pos.market_value if pos else 0.0
        delta = w * acct.equity - held_val
        if abs(delta) < limits.min_order_usd:
            continue
        side = "buy" if delta > 0 else "sell"
        verdict = None
        if side == "buy":
            if not allowed:
                log(sym, "skip", 0, price, note=why)
                continue
            verdict = gate(sym)
            if verdict.action == "veto":
                log(sym, "skip", 0, price, verdict, "news veto")
                continue
            if verdict.action == "reduce":
                delta *= 0.5
        if side == "sell" and w == 0.0 and pos:
            qty = pos.qty
        else:
            qty = abs(delta) / price
            qty = round(qty, 6) if is_crypto else int(qty)
            if side == "sell" and pos:
                qty = min(qty, pos.qty)
        if qty <= 0:
            continue
        order_id = ""
        if not dry_run:
            res = broker.submit_order(sym, qty, side,
                                      time_in_force="gtc" if is_crypto else "day",
                                      client_order_id=f"{key}:{_norm(sym)}:{side}")
            order_id = res.order_id
        log(sym, side, qty, price, verdict, notes.get(sym, ""), order_id)

    if not dry_run:
        save_state(state_path, state)
    return rows
