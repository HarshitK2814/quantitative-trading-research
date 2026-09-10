"""Publish a sanitised, read-only snapshot of the paper account as JSON.

Writes ``live.json`` for the public dashboard to consume.

Security model -- the reason this script exists at all
------------------------------------------------------
The public page must never hold Alpaca credentials. An API key in page source
is readable by every visitor, and Alpaca keys can **place and cancel orders**,
not merely read state. Exposing one would let anyone corrupt the trade journal
that this project's entire credibility rests on.

So the split is:

* **This script** runs where the secret is safe (GitHub Actions, key supplied
  from repository secrets) and talks to Alpaca.
* **The page** fetches only the JSON this script emits, and never sees a
  credential.

Everything written here is deliberately read-only and non-sensitive: balances,
positions, and price history. No key, no account identifiers beyond the
already-public account number, no order-submission capability.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import requests

BASE = "https://paper-api.alpaca.markets"
STRATEGY = "H1-momentum-126-21-k5-monthly"
STARTING_CAPITAL = 100_000.0

# (label, Alpaca period, Alpaca timeframe) -- mirrors the ranges a broker UI
# offers, so the page can switch between them without refetching.
RANGES = [
    ("1D", "1D", "5Min"),
    ("1W", "1W", "15Min"),
    ("1M", "1M", "1D"),
    ("ALL", "3M", "1D"),
]


def _headers() -> dict[str, str]:
    """Build auth headers from the environment. Never logged, never emitted."""
    key = os.environ.get("ALPACA_API_KEY_ID", "").strip()
    secret = os.environ.get("ALPACA_API_SECRET_KEY", "").strip()
    if not key or not secret:
        raise RuntimeError(
            "Alpaca paper credentials missing from the environment. In CI "
            "these come from repository secrets; locally from .env."
        )
    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "accept": "application/json",
    }


def _get(session: requests.Session, path: str, **params) -> dict | list:
    """GET a paper-API path, refusing any non-paper base URL."""
    if not BASE.startswith("https://paper-api."):
        raise RuntimeError(f"Refusing non-paper endpoint: {BASE!r}")
    r = session.get(f"{BASE}{path}", params=params or None, timeout=30)
    r.raise_for_status()
    return r.json() if r.content else {}


def collect() -> dict:
    """Gather everything the dashboard needs, in one pass."""
    session = requests.Session()
    session.headers.update(_headers())

    account = _get(session, "/v2/account")
    positions = _get(session, "/v2/positions") or []
    clock = _get(session, "/v2/clock")
    orders = _get(session, "/v2/orders", status="all", limit=25, direction="desc")

    equity = float(account["equity"])
    last_equity = float(account["last_equity"])

    history = {}
    for label, period, timeframe in RANGES:
        try:
            h = _get(session, "/v2/account/portfolio/history",
                     period=period, timeframe=timeframe, extended_hours="true")
            pts = [
                {"t": t, "e": e}
                for t, e in zip(h.get("timestamp", []), h.get("equity", []),
                                strict=False)
                if e  # Alpaca pads pre-inception buckets with 0.0; drop them
            ]
            history[label] = {"points": pts,
                              "base": float(h.get("base_value") or 0.0)}
        except Exception as exc:  # noqa: BLE001 - one bad range must not kill the feed
            history[label] = {"points": [], "base": 0.0, "error": str(exc)}

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "strategy": STRATEGY,
        "paper": True,
        "account": {
            "number": account.get("account_number"),
            "status": account.get("status"),
            "equity": equity,
            "last_equity": last_equity,
            "cash": float(account["cash"]),
            "buying_power": float(account["buying_power"]),
            "day_change": equity - last_equity,
            "day_change_pct": (equity / last_equity - 1.0) if last_equity else 0.0,
            "total_change": equity - STARTING_CAPITAL,
            "total_change_pct": equity / STARTING_CAPITAL - 1.0,
            "starting_capital": STARTING_CAPITAL,
            "options_level": int(account.get("options_approved_level") or 0),
        },
        "market": {
            "is_open": bool(clock.get("is_open")),
            "next_open": clock.get("next_open"),
            "next_close": clock.get("next_close"),
        },
        "positions": [
            {
                "symbol": p["symbol"],
                "qty": float(p["qty"]),
                "avg_entry_price": float(p["avg_entry_price"]),
                "current_price": float(p["current_price"]),
                "market_value": float(p["market_value"]),
                "unrealized_pl": float(p["unrealized_pl"]),
                "unrealized_plpc": float(p["unrealized_plpc"]),
                "asset_class": p.get("asset_class", "us_equity"),
            }
            for p in positions
        ],
        "orders": [
            {
                "symbol": o["symbol"],
                "side": o["side"],
                "qty": float(o.get("qty") or 0),
                "filled_qty": float(o.get("filled_qty") or 0),
                "filled_avg_price": (float(o["filled_avg_price"])
                                     if o.get("filled_avg_price") else None),
                "status": o["status"],
                "submitted_at": o.get("submitted_at"),
                "asset_class": o.get("asset_class", "us_equity"),
            }
            for o in (orders or [])
        ],
        "history": history,
    }


def main() -> None:
    """Write live.json next to the dashboard."""
    out = Path(os.environ.get("LIVE_JSON_PATH", "live.json"))
    payload = collect()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    acct = payload["account"]
    print(f"Wrote {out} | equity ${acct['equity']:,.2f} "
          f"({acct['day_change_pct']:+.2%} today) "
          f"| {len(payload['positions'])} positions "
          f"| market_open={payload['market']['is_open']}")


if __name__ == "__main__":
    main()
