"""Pure planning for the options sleeve (O1 hedge, O2 put credit spread).

Rules are pre-registered in research/hypotheses_sessions.md. Forward test
only: there is no option price history, so nothing here is validated.
No I/O in this module; the session step does the broker calls.
"""

from __future__ import annotations

import dataclasses
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from src.broker import OptionContract, OptionQuote, Position
from src.intraday.strategies import StrategySpec, target_weights

TOTAL_CAP_PCT = 0.02
CAP_PCT = {"hedge": 0.01, "spread": 0.01}

SPREAD_UNDERLYINGS = ("SPY", "QQQ")
HEDGE_UNDERLYING = "SPY"
SHORT_OTM = 0.05
SHORT_OTM_TOL = 0.01   # short strike must sit 4-6% below spot
SPREAD_WIDTH = 5.0
SPREAD_MIN_DTE = 30
SPREAD_MAX_DTE = 45
MIN_CREDIT_FRAC = 0.20
MAX_OPEN_SPREADS = 2
PROFIT_TAKE_FRAC = 0.50
CLOSE_DTE = 7
STOP_MULT = 2.0
QUOTE_MAX_AGE_MIN = 15

_EPS = 1e-9
_DONE = {"canceled", "expired", "rejected", "done_for_day"}


def _floor_cent(x: float) -> float:
    return math.floor(x * 100 + 1e-6) / 100


def _ceil_cent(x: float) -> float:
    return math.ceil(x * 100 - 1e-6) / 100


# -- risk -------------------------------------------------------------------------

def spread_max_loss(width: float, credit: float, contracts: int) -> float:
    """Worst-case loss of a put credit spread, in dollars."""
    return round((width - credit) * 100.0 * contracts, 2)


def risk_used(opts: dict) -> tuple[float, float]:
    """(hedge premium at risk, spread max loss) over every tracked entry."""
    hedge = sum(float(h.get("cost_basis", 0.0)) for h in opts.get("hedges", {}).values())
    spread = sum(float(s.get("max_loss", 0.0)) for s in opts.get("spreads", {}).values())
    return hedge, spread


def budget(opts: dict, equity: float, kind: str) -> float:
    """Dollars of new risk allowed for `kind` ("hedge" | "spread")."""
    hedge, spread = risk_used(opts)
    bucket = hedge if kind == "hedge" else spread
    room = min(CAP_PCT[kind] * equity - bucket, TOTAL_CAP_PCT * equity - hedge - spread)
    return max(room, 0.0)


def risk_check(opts: dict, equity: float, kind: str, new_risk: float) -> tuple[bool, str]:
    """May a new position adding `new_risk` dollars open? Closes never call this."""
    if equity <= 0:
        return False, "no equity"
    hedge, spread = risk_used(opts)
    if hedge + spread >= TOTAL_CAP_PCT * equity - _EPS:
        return False, "options risk at 2% cap"
    if new_risk > budget(opts, equity, kind) + _EPS:
        return False, f"{kind} would breach risk cap (1% {kind}, 2% total)"
    return True, "ok"


# -- quotes -----------------------------------------------------------------------

def quote_ok(quote: OptionQuote | None, now: datetime) -> bool:
    """A usable quote: present, timestamped, fresh, not crossed, ask > 0."""
    if quote is None or quote.timestamp is None:
        return False
    if (now - quote.timestamp) > timedelta(minutes=QUOTE_MAX_AGE_MIN):
        return False
    return quote.ask > 0 and quote.bid >= 0 and quote.ask >= quote.bid


# -- O2 spread selection ----------------------------------------------------------

@dataclass(frozen=True)
class SpreadPlan:
    """One bull put spread candidate (per-share prices)."""

    underlying: str
    short_symbol: str
    long_symbol: str
    short_strike: float
    long_strike: float
    expiry: date
    width: float
    credit: float

    @property
    def max_loss_per_contract(self) -> float:
        return spread_max_loss(self.width, self.credit, 1)


def select_spread(
    contracts: list[OptionContract], quotes: dict[str, OptionQuote],
    spot: float, as_of: date, now: datetime,
) -> tuple[SpreadPlan | None, str]:
    """Pick the spread per the fixed rule, or (None, reason)."""
    if spot <= 0:
        return None, "no spot price"
    lo, hi = as_of + timedelta(days=SPREAD_MIN_DTE), as_of + timedelta(days=SPREAD_MAX_DTE)
    puts = [c for c in contracts
            if c.option_type == "put" and c.tradable and lo <= c.expiration_date <= hi]
    if not puts:
        return None, "no 30-45 DTE puts"
    expiry = min(c.expiration_date for c in puts)
    chain = {c.strike_price: c for c in puts if c.expiration_date == expiry}
    target = spot * (1 - SHORT_OTM)
    pairs = [k for k in chain if (k - SPREAD_WIDTH) in chain
             and abs(k - target) <= SHORT_OTM_TOL * spot + _EPS]
    if not pairs:
        return None, "no strike pair $5 apart with short 4-6% below spot"
    short_k = min(pairs, key=lambda k: abs(k - target))
    long_k = short_k - SPREAD_WIDTH
    short_c, long_c = chain[short_k], chain[long_k]
    sq, lq = quotes.get(short_c.symbol), quotes.get(long_c.symbol)
    if not (quote_ok(sq, now) and quote_ok(lq, now)):
        return None, "missing or stale quote"
    credit = _floor_cent(sq.mid - lq.mid)
    if credit < MIN_CREDIT_FRAC * SPREAD_WIDTH - _EPS:
        return None, f"credit {credit:.2f} < 20% of width"
    return SpreadPlan(short_c.underlying_symbol, short_c.symbol, long_c.symbol,
                      short_k, long_k, expiry, SPREAD_WIDTH, credit), "ok"


def size_contracts(per_contract_risk: float, room: float) -> int:
    """Whole contracts that fit in `room` dollars of risk."""
    if per_contract_risk <= 0:
        return 0
    return int(math.floor(room / per_contract_risk + _EPS))


def spread_legs(short_symbol: str, long_symbol: str, opening: bool) -> list[dict]:
    """Both legs of the spread, for one multi-leg order. Always two legs."""
    if opening:
        return [
            {"symbol": short_symbol, "side": "sell", "position_intent": "sell_to_open"},
            {"symbol": long_symbol, "side": "buy", "position_intent": "buy_to_open"},
        ]
    return [
        {"symbol": short_symbol, "side": "buy", "position_intent": "buy_to_close"},
        {"symbol": long_symbol, "side": "sell", "position_intent": "sell_to_close"},
    ]


def spread_open_allowed(trend_is_long: bool, news_action: str | None,
                        n_open: int) -> tuple[bool, str]:
    """Open only on S1 long AND news ok AND fewer than 2 spreads."""
    if n_open >= MAX_OPEN_SPREADS:
        return False, "max 2 spreads open"
    if not trend_is_long:
        return False, "S1 trend not long"
    if news_action != "ok":
        return False, f"news gate {news_action or 'missing'}"
    return True, "ok"


def trend_long(spec: StrategySpec, close: pd.Series | None, as_of: date) -> bool:
    """S1 trend signal for one ETF. Missing or stale data means not long."""
    if close is None:
        return False
    sym = spec.symbols[0]
    one = dataclasses.replace(spec, symbols=(sym,), active=True)
    return target_weights({"x": one}, {sym: close}, as_of=as_of).get(sym, 0.0) > 0


# -- O2 close rules ---------------------------------------------------------------

def close_reason(spread: dict, short_q: OptionQuote | None, long_q: OptionQuote | None,
                 as_of: date, now: datetime) -> tuple[str | None, float | None]:
    """("dte" | "profit" | "stop" | None, mid value of the spread)."""
    dte = (date.fromisoformat(spread["expiry"]) - as_of).days
    if not (quote_ok(short_q, now) and quote_ok(long_q, now)):
        return ("dte" if dte <= CLOSE_DTE else None), None
    value = short_q.mid - long_q.mid
    credit = float(spread["credit"])
    if dte <= CLOSE_DTE:
        return "dte", value
    if value <= credit * (1 - PROFIT_TAKE_FRAC) + _EPS:
        return "profit", value
    if value >= credit * STOP_MULT - _EPS:
        return "stop", value
    return None, value


def close_debit(short_q: OptionQuote, long_q: OptionQuote, width: float) -> float:
    """Limit debit to close: natural price (short ask - long bid), capped at width."""
    return min(_ceil_cent(max(short_q.ask - long_q.bid, 0.01)), width)


# -- O1 hedge cap -----------------------------------------------------------------

def hedge_contracts(planned: int, premium_per_contract: float, room: float) -> int:
    """Cut the hedge.py size so total premium fits the 1% budget."""
    return max(0, min(planned, size_contracts(premium_per_contract, room)))


# -- state reconciliation ---------------------------------------------------------

def _filled_qty(order: dict) -> int:
    return int(float(order.get("filled_qty") or 0))


def _filled_price(order: dict) -> float | None:
    raw = order.get("filled_avg_price")
    return abs(float(raw)) if raw not in (None, "") else None


def reconcile_spread(entry: dict, order: dict | None) -> dict | None:
    """New entry after reading its order; None means it is gone from the book."""
    if order is None:
        return entry
    status, n = order.get("status"), _filled_qty(order)
    e = dict(entry)
    if e["status"] == "pending_open":
        if status == "filled" or (status in _DONE and n > 0):
            e["status"] = "open"
            e["contracts"] = n or e["contracts"]
            price = _filled_price(order)
            if price is not None:
                e["credit"] = price
            e["max_loss"] = spread_max_loss(e["width"], e["credit"], e["contracts"])
            return e
        return None if status in _DONE else entry
    if e["status"] == "pending_close":
        if status == "filled":
            return None
        if status in _DONE:
            left = e["contracts"] - n
            if left <= 0:
                return None
            e.update(status="open", contracts=left,
                     max_loss=spread_max_loss(e["width"], e["credit"], left))
            return e
    return entry


def reconcile_hedge(entry: dict, order: dict | None) -> dict | None:
    """Same as reconcile_spread, for a long put hedge."""
    if order is None:
        return entry
    status, n = order.get("status"), _filled_qty(order)
    e = dict(entry)
    if e["status"] == "pending_open":
        if status == "filled" or (status in _DONE and n > 0):
            price = _filled_price(order)
            e["qty"] = n or e["qty"]
            if price is not None:
                e["cost_basis"] = round(price * 100.0 * e["qty"], 2)
            e["status"] = "open"
            return e
        return None if status in _DONE else entry
    if e["status"] == "pending_close":
        if status == "filled":
            return None
        if status in _DONE:
            left = e["qty"] - n
            if left <= 0:
                return None
            e["cost_basis"] = float(e["cost_basis"]) * left / e["qty"]
            e.update(status="open", qty=left)
            return e
    return entry


def legs_held(spread: dict, positions: dict[str, Position]) -> bool:
    """Both legs held at exactly the spread size: short = -contracts, long = +contracts."""
    s, lg = positions.get(spread["short"]), positions.get(spread["long"])
    n = int(spread["contracts"])
    return bool(s and lg and int(round(s.qty)) == -n and int(round(lg.qty)) == n)


def naked_short_qty(spread: dict, positions: dict[str, Position]) -> int:
    """Short contracts held with no matching long leg (must be bought back)."""
    s, lg = positions.get(spread["short"]), positions.get(spread["long"])
    if not s or s.qty >= 0:
        return 0
    covered = max(int(round(lg.qty)), 0) if lg else 0
    return max(int(round(-s.qty)) - covered, 0)


# -- submit errors and unknown outcomes -------------------------------------------

def classify_submit_error(exc: BaseException) -> str:
    """"rejected" only when the order surely was not placed (HTTP 4xx or local
    validation); anything else (5xx, timeout, network) is "unknown"."""
    if isinstance(exc, ValueError):
        return "rejected"
    m = re.search(r"HTTP (\d{3})", str(exc))
    if isinstance(exc, RuntimeError) and m and 400 <= int(m.group(1)) < 500:
        return "rejected"
    return "unknown"


def resolve_unknown(entry: dict, order: dict | None, reconcile) -> dict | None:
    """Turn an "unknown" entry back into its pending state using the order
    found by client id, then reconcile it. None order = still unknown."""
    if order is None:
        return entry
    e = {k: v for k, v in entry.items() if k != "unknown_of"}
    e["status"] = entry["unknown_of"]
    id_key = "close_order_id" if e["status"] == "pending_close" else "order_id"
    if order.get("id"):
        e[id_key] = order["id"]
    return reconcile(e, order)


# -- orphans (broker holds O1/O2-like things the state does not know) -------------

_OCC_PUT = re.compile(r"^(SPY|QQQ)\d{6}P\d{8}$")


def _known(opts: dict) -> tuple[set[str], set[str]]:
    syms, ids = set(), set()
    for s in opts.get("spreads", {}).values():
        syms.update(x for x in (s.get("short"), s.get("long")) if x)
        ids.update(v for k, v in s.items() if k.endswith("order_id") and v)
    for hid, h in opts.get("hedges", {}).items():
        syms.add(hid)
        ids.update(v for k, v in h.items() if k.endswith("order_id") and v)
    return syms, ids


def find_orphans(opts: dict, positions: dict[str, Position],
                 open_orders: list[dict]) -> list[str]:
    """SPY/QQQ put positions or open orders (by symbol or O1/O2 client id)
    that state does not track. Any hit means state may be out of sync."""
    syms, ids = _known(opts)
    out = [f"position {s}" for s in positions if _OCC_PUT.match(s) and s not in syms]
    for od in open_orders:
        if od.get("id") in ids or od.get("client_order_id") in ids:
            continue
        coid = od.get("client_order_id") or ""
        legs = [lg.get("symbol", "") for lg in (od.get("legs") or [])]
        if ":O1:" in coid or ":O2:" in coid or any(
                _OCC_PUT.match(x or "") and x not in syms
                for x in [od.get("symbol", "")] + legs):
            out.append(f"order {od.get('id')} ({coid})")
    return out


# -- reconcile log rows -------------------------------------------------------------

def _pnl(kind: str, before: dict, price: float | None, n: int) -> float | None:
    if price is None or n <= 0:
        return None
    if kind == "spread":
        return round((float(before["credit"]) - price) * 100.0 * n, 2)
    per_share_cost = float(before["cost_basis"]) / (100.0 * before["qty"])
    return round((price - per_share_cost) * 100.0 * n, 2)


def describe_reconcile(kind: str, before: dict, after: dict | None,
                       order: dict | None) -> dict | None:
    """Log row (side, qty, price, note) for what a reconcile changed, or None."""
    if order is None:
        return None
    status, price = order.get("status"), _filled_price(order)
    size = "contracts" if kind == "spread" else "qty"
    total = int(before[size])
    if before["status"] == "pending_open":
        if after is None:
            return {"side": "unfilled", "qty": 0, "price": 0.0,
                    "note": f"open not filled ({status}); no position"}
        if after["status"] == "open":
            n = int(after[size])
            if kind == "spread":
                note = (f"open filled {n}/{total} credit={after['credit']:.2f} "
                        f"max_loss={after['max_loss']:.0f}")
            else:
                note = (f"open filled {n}/{total} debit={price if price is not None else 'n/a'} "
                        f"cost={float(after['cost_basis']):.0f}")
            if status != "filled":
                note = f"partial {note}; rest {status}"
            return {"side": "fill", "qty": n, "price": price or 0.0, "note": note}
    elif before["status"] == "pending_close":
        closed = total if after is None else total - int(after[size])
        if closed > 0:
            pnl = _pnl(kind, before, price, closed)
            pnl_s = "n/a" if pnl is None else f"{pnl:.2f}"
            note = (f"close filled {closed}/{total} price={price if price is not None else 'n/a'} "
                    f"realised_pnl={pnl_s}")
            if after is not None:
                note = f"partial {note}; rest {status}, still open"
            return {"side": "close_fill", "qty": closed, "price": price or 0.0, "note": note}
        if after is not None and after["status"] == "open":
            return {"side": "unfilled", "qty": 0, "price": 0.0,
                    "note": f"close not filled ({status}); still open"}
    if status == "partially_filled":
        return {"side": "partial", "qty": int(float(order.get("filled_qty") or 0)),
                "price": price or 0.0,
                "note": f"partially filled {order.get('filled_qty')}/{total}, still working"}
    return None
