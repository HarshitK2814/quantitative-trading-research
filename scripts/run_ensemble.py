"""Trade the frozen ensemble on the Alpaca PAPER account.

    PYTHONPATH=. python scripts/run_ensemble.py            # dry run
    PYTHONPATH=. python scripts/run_ensemble.py --execute
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from src.broker import AlpacaPaperBroker
from src.config import load_broker_config
from src.search.engine import cap_gross, cost_table, run_weights
from src.search.ensemble import ensemble_weights, kill_scale, latest_target, to_alpaca
from src.search.families import S2, Ctx, Trial
from src.search.universe import CRYPTO, ETFS, load_panel, sp500_membership, top_liquid

CFG = Path("portfolio/ensemble.json")
STATE = Path("portfolio/ensemble_state.json")
LOG = Path("portfolio/ensemble_trades.csv")
MIN_ORDER = 50.0


def owned_symbols() -> set[str]:
    """Alpaca symbols the ensemble may trade (read by run_session to avoid overlap)."""
    if not CFG.exists():
        return set()
    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    return set(st.get("owned", []))


def is_option_symbol(sym: str) -> bool:
    return len(sym) > 10 and any(c.isdigit() for c in sym)


def plan_orders(target, positions, prices, equity, stale, owned=None) -> list:
    """Pure order planner. Returns (sell_first, sym, side, qty, px) tuples.
    stale symbols (missing last bar) are held; option symbols are never touched."""
    owned = set(owned if owned is not None else target) | set(target)
    orders = []
    for sym in sorted(owned):
        if is_option_symbol(sym):
            continue
        if sym in stale:
            print("stale, hold", sym)
            continue
        key = sym.replace("/", "")
        held = positions.get(key)
        px = prices.get(sym) or (held.current_price if held else None)
        if not px:
            continue
        tgt = target.get(sym, 0.0)
        if tgt == 0 and held is not None and held.qty:
            if held.qty > 0:
                orders.append((0, sym, "sell", abs(held.qty), px))
            continue
        held_val = held.market_value if held else 0.0
        delta = tgt * equity - held_val
        if abs(delta) < MIN_ORDER:
            continue
        side = "buy" if delta > 0 else "sell"
        qty = round(abs(delta) / px, 6) if "/" in sym else int(abs(delta) / px)
        if qty > 0:
            orders.append((0 if side == "sell" else 1, sym, side, qty, px))
    return orders


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    cfg = json.loads(CFG.read_text())
    trials = [Trial(t["name"], t["family"], t["params"]) for t in cfg["trials"]]
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    broker = AlpacaPaperBroker(load_broker_config())
    acct = broker.get_account()
    scale = kill_scale(acct.equity, state)

    members = sp500_membership()
    close, vol = load_panel(sorted(set(members.columns) | set(ETFS) | set(CRYPTO) | set(S2)))
    today = datetime.now(UTC).date()
    close = close[close.index.date < today]          # completed bars only
    vol = vol.reindex_like(close)
    liquid = top_liquid(close, vol, members.reindex(close.index).ffill().fillna(False), n=150)
    ctx = Ctx(close=close, members=members, liquid=liquid)
    bps = cost_table(close.columns)
    sw, sr = {}, {}
    for t in trials:
        w = cap_gross(t.weights(ctx).fillna(0.0))
        sw[t.name] = w
        sr[t.name] = run_weights(w, close[w.columns], bps=bps[w.columns])
    if trials:
        tgt = latest_target(ensemble_weights(sw, sr, close, bps, cfg.get("vol_target", 0.10))) * scale
        target = {to_alpaca(k): float(v) for k, v in tgt.items()}
    else:
        target = {}

    positions = {p.symbol: p for p in broker.get_positions().values()}
    owned = {x for x in set(state.get("owned", [])) | set(target) if not is_option_symbol(x)}
    prices = broker.get_last_prices(sorted(s for s in owned if "/" not in s))
    market_open = broker.is_market_open()
    stale = {c for c in close.columns if close[c].iloc[-1] != close[c].iloc[-1]}
    stale = {to_alpaca(c) for c in stale}
    orders = plan_orders(target, positions, prices, acct.equity, stale, owned)
    gross = sum(abs(v) for v in target.values())
    mx = max((abs(v) for v in target.values()), default=0.0)
    print(f"equity {acct.equity:,.2f} scale {scale} targets {len(target)} "
          f"gross {gross:.3f} max|w| {mx:.3f} orders {len(orders)}")
    ts = datetime.now(UTC).isoformat()
    for _, sym, side, qty, px in sorted(orders):      # sells first
        is_crypto = "/" in sym
        if args.execute and not is_crypto and not market_open:
            print("market closed, skip", sym)
            continue
        oid = ""
        if args.execute:
            try:
                res = broker.submit_order(sym, qty, side,
                                          time_in_force="gtc" if is_crypto else "day",
                                          client_order_id=f"ens:{today}:{sym.replace('/', '')}:{side}")
                oid = res.order_id
            except Exception as exc:  # noqa: BLE001 - log and continue
                print("ORDER FAILED", side, qty, sym, str(exc)[:150])
                continue
        print(side, qty, sym, f"~{px:.2f}", oid or ("(dry run)" + ("" if market_open or is_crypto else ", market closed")))
        if args.execute:
            new = not LOG.exists()
            with LOG.open("a", newline="") as fh:
                wr = csv.writer(fh)
                if new:
                    wr.writerow(["ts", "symbol", "side", "qty", "ref_price", "order_id"])
                wr.writerow([ts, sym, side, qty, px, oid])
    if args.execute:
        state["owned"] = sorted(s for s in owned if abs(target.get(s, 0.0)) > 0
                                or s.replace("/", "") in positions)
        STATE.write_text(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
