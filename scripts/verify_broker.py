"""Verify the Alpaca paper connection and prove the safety interlock works.

Run this after filling in ``.env``:

    PYTHONPATH=. python scripts/verify_broker.py

It does three things, in order:

1.  Proves the interlock refuses a live endpoint and refuses a missing/false
    paper flag. These assertions run first, so a broken interlock is caught
    before any real credential is used.
2.  Loads paper credentials and calls ``GET /v2/account``.
3.  Prints a redacted summary of the account.

No secret is ever printed. The key id is shown as a short prefix only, which is
enough to confirm *which* key is in use without disclosing it.
"""

from __future__ import annotations

import sys

import requests

from src.config import (
    ALPACA_PAPER_ENDPOINT,
    RISK,
    BrokerConfig,
    LiveTradingBlockedError,
    assert_paper_only,
    load_broker_config,
)

TIMEOUT_SECONDS = 30


def check_interlock() -> None:
    """Assert the safety interlock rejects everything except the paper setup."""
    print("=" * 70)
    print("1. SAFETY INTERLOCK")
    print("=" * 70)

    must_fail: list[tuple[str, str | None, str]] = [
        ("https://api.alpaca.markets", "true", "Alpaca LIVE endpoint"),
        ("https://paper-api.alpaca.market", "true", "typo (missing 's')"),
        ("https://paper-api.alpaca.markets.evil.com", "true", "look-alike domain"),
        ("https://data.alpaca.markets", "true", "wrong Alpaca service"),
        (ALPACA_PAPER_ENDPOINT, "false", "paper flag set to false"),
        (ALPACA_PAPER_ENDPOINT, None, "paper flag unset"),
    ]

    for url, flag, label in must_fail:
        try:
            assert_paper_only(url, flag)
        except LiveTradingBlockedError:
            print(f"  [BLOCKED] {label}")
        else:
            print(f"  [FAIL!!!] {label} was ALLOWED. Stopping.")
            sys.exit(1)

    assert_paper_only(ALPACA_PAPER_ENDPOINT, "true")
    print(f"  [ALLOWED] {ALPACA_PAPER_ENDPOINT} with PAPER_TRADING_ONLY=true")
    print("  -> Interlock behaving correctly (allow-list, fails closed).\n")


def fetch_account(broker: BrokerConfig) -> dict:
    """Call the paper account endpoint and return the parsed payload."""
    response = requests.get(
        f"{broker.base_url}/v2/account",
        headers={
            "APCA-API-KEY-ID": broker.api_key_id,
            "APCA-API-SECRET-KEY": broker.api_secret_key,
        },
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code == 403:
        raise SystemExit(
            "403 Forbidden. The credentials were rejected. Most likely causes:\n"
            "  - keys were regenerated in the dashboard (the old pair is dead)\n"
            "  - live keys pasted against the paper endpoint\n"
            "  - a stray space or newline in .env\n"
            f"  - X-Request-ID for support: {response.headers.get('X-Request-ID')}"
        )
    response.raise_for_status()
    return response.json()


def main() -> None:
    """Run the interlock checks, then verify the live paper connection."""
    check_interlock()

    print("=" * 70)
    print("2. PAPER ACCOUNT CONNECTION")
    print("=" * 70)

    broker = load_broker_config()
    # Deliberately partial: enough to identify the key, not enough to use it.
    print(f"  Endpoint : {broker.base_url}")
    print(f"  Key id   : {broker.api_key_id[:6]}...{broker.api_key_id[-2:]} (redacted)")
    print(f"  Repr     : {broker!r}")
    print()

    account = fetch_account(broker)

    equity = float(account["equity"])
    cash = float(account["cash"])
    buying_power = float(account["buying_power"])

    print("=" * 70)
    print("3. ACCOUNT SUMMARY")
    print("=" * 70)
    print(f"  Account number : {account.get('account_number')}")
    print(f"  Status         : {account.get('status')}")
    print(f"  Currency       : {account.get('currency')}")
    print(f"  Equity         : ${equity:,.2f}")
    print(f"  Cash           : ${cash:,.2f}")
    print(f"  Buying power   : ${buying_power:,.2f}")
    print(f"  Pattern day tr.: {account.get('pattern_day_trader')}")
    print(f"  Trading blocked: {account.get('trading_blocked')}")
    print()

    # The platform offers intraday margin. This project does not use it. Sizing
    # is against cash, never buying power -- so record the discrepancy loudly
    # rather than letting a future bug quietly spend it.
    if buying_power > cash:
        leverage = buying_power / cash if cash else float("inf")
        print(
            f"  NOTE: buying power is {leverage:.1f}x cash (platform margin).\n"
            f"        This project is long-only and unlevered "
            f"(max_gross_exposure={RISK.max_gross_exposure:.2f}).\n"
            f"        Position sizing uses CASH (${cash:,.0f}), not buying power."
        )
        print()

    if account.get("status") != "ACTIVE":
        print(f"  WARNING: account status is {account.get('status')!r}, not ACTIVE.")

    print("PAPER TRADING CONNECTION VERIFIED. No real money is involved.")


if __name__ == "__main__":
    main()
