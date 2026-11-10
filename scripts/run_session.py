"""Run one trading session on the user's existing Alpaca PAPER account.

The account is shared with the retired H1 sleeve.

    PYTHONPATH=. python scripts/run_session.py                 # dry run, auto session
    PYTHONPATH=. python scripts/run_session.py --execute       # submit paper orders
    PYTHONPATH=. python scripts/run_session.py --session open  # force a session
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from src.broker import AlpacaPaperBroker
from src.config import PROJECT_ROOT, load_broker_config
from src.intraday.groq_gate import review_trade
from src.intraday.limits import SessionLimits
from src.intraday.news import fetch_headlines
from src.intraday.prices import crypto_last_prices, load_daily_closes
from src.intraday.schedule import current_session
from src.intraday.session import run_session
from src.intraday.strategies import REGISTRY

STATE = PROJECT_ROOT / "portfolio" / "session_state.json"
LOG = PROJECT_ROOT / "portfolio" / "session_log.csv"


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--session")
    args = ap.parse_args()

    now = datetime.now(UTC)
    name = args.session or current_session(now)
    if name is None:
        print("No session due now; exiting.")
        return

    cfg = load_broker_config()
    broker = AlpacaPaperBroker(cfg)
    symbols = [s for spec in REGISTRY.values() if spec.active for s in spec.symbols]
    if not symbols:
        print("No active strategies (none passed the gate yet); exiting.")
        return
    stocks = [s for s in symbols if "/" not in s]
    crypto = [s for s in symbols if "/" in s]

    closes = load_daily_closes(symbols)
    prices = broker.get_last_prices(stocks) if stocks else {}
    prices |= crypto_last_prices(crypto, cfg.api_key_id, cfg.api_secret_key)
    headlines = fetch_headlines(symbols)
    groq_key = os.environ.get("GROQ_API_KEY", "")

    rows = run_session(
        name=name, broker=broker, closes=closes, now_utc=now, limits=SessionLimits(),
        state_path=Path(STATE), log_path=Path(LOG), registry=REGISTRY,
        gate=lambda sym: review_trade(sym, headlines.get(sym), groq_key),
        prices=prices, dry_run=not args.execute,
    )
    for r in rows:
        print(r["session"], r["symbol"], r["side"], r["qty"], r["note"], r["news_action"])
    print(f"{len(rows)} action(s) in session {name!r} (dry_run={not args.execute})")


if __name__ == "__main__":
    main()
