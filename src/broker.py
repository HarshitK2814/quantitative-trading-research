"""Alpaca **paper** broker client.

Every method here routes through :func:`src.config.load_broker_config`, which
refuses to return credentials unless the endpoint is the paper endpoint and
``PAPER_TRADING_ONLY`` is true. There is no code path in this module that can
reach a live-money account.

Design notes
------------
A thin REST wrapper is used rather than ``alpaca-py``. The reasons are specific
rather than dogmatic:

* The project needs exactly five operations (clock, account, positions, submit,
  list orders). A dependency is not warranted for that.
* Every request goes through :meth:`AlpacaPaperBroker._request`, which is a
  single auditable place to enforce the paper endpoint at call time -- not just
  at construction time.
* Fewer moving parts between the research and the order.

``alpaca-py`` remains the right choice for anything needing streaming, complex
order types, or the full asset universe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

import requests

from src.config import (
    ALPACA_PAPER_ENDPOINT,
    BrokerConfig,
    LiveTradingBlockedError,
    load_broker_config,
)

logger = logging.getLogger(__name__)

OrderSide = Literal["buy", "sell"]
TimeInForce = Literal["day", "gtc", "opg", "cls"]

_TIMEOUT = 30


@dataclass(frozen=True)
class Position:
    """A single open position."""

    symbol: str
    qty: float
    market_value: float
    avg_entry_price: float
    current_price: float
    unrealised_pl: float


@dataclass(frozen=True)
class AccountSnapshot:
    """Point-in-time account state."""

    account_number: str
    equity: float
    last_equity: float
    cash: float
    buying_power: float
    status: str
    trading_blocked: bool
    taken_at: datetime


@dataclass(frozen=True)
class OrderResult:
    """Outcome of an order submission."""

    order_id: str
    client_order_id: str
    symbol: str
    side: str
    qty: float
    order_type: str
    time_in_force: str
    status: str
    submitted_at: str
    filled_qty: float
    filled_avg_price: float | None


class AlpacaPaperBroker:
    """Minimal REST client for the Alpaca **paper** trading API."""

    def __init__(self, config: BrokerConfig | None = None) -> None:
        """Load and validate paper credentials.

        Raises:
            LiveTradingBlockedError: If the environment is not paper-only.

        """
        self._config = config or load_broker_config()
        # Re-assert at construction: a caller could hand in a hand-built config.
        if self._config.base_url.rstrip("/") != ALPACA_PAPER_ENDPOINT:
            raise LiveTradingBlockedError(
                f"Broker refused: {self._config.base_url!r} is not the paper "
                f"endpoint {ALPACA_PAPER_ENDPOINT!r}."
            )
        self._session = requests.Session()
        self._session.headers.update(
            {
                "APCA-API-KEY-ID": self._config.api_key_id,
                "APCA-API-SECRET-KEY": self._config.api_secret_key,
                "accept": "application/json",
            }
        )

    def __repr__(self) -> str:  # pragma: no cover - trivial
        """Render without exposing credentials."""
        return f"AlpacaPaperBroker(endpoint={self._config.base_url!r}, PAPER)"

    # -- internals ---------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Issue one request, re-checking the paper endpoint at call time.

        The endpoint check is repeated here rather than trusted from
        construction, so that no future refactor can introduce a path that
        reaches a live URL through an already-built client.
        """
        base = self._config.base_url.rstrip("/")
        if base != ALPACA_PAPER_ENDPOINT:
            raise LiveTradingBlockedError(
                f"Refusing request to non-paper endpoint {base!r}."
            )
        url = f"{base}{path}"
        response = self._session.request(method, url, timeout=_TIMEOUT, **kwargs)

        if response.status_code >= 400:
            request_id = response.headers.get("X-Request-ID", "n/a")
            # Body may echo request fields but never credentials (they are
            # headers), so including it is safe and aids diagnosis.
            raise RuntimeError(
                f"Alpaca {method} {path} failed: HTTP {response.status_code} "
                f"{response.text[:300]} (X-Request-ID: {request_id})"
            )
        return response.json() if response.content else None

    # -- read --------------------------------------------------------------

    def is_market_open(self) -> bool:
        """Return whether the US equity market is open right now."""
        return bool(self._request("GET", "/v2/clock")["is_open"])

    def clock(self) -> dict[str, Any]:
        """Return the raw market clock (open flag, next open, next close)."""
        return self._request("GET", "/v2/clock")

    def get_account(self) -> AccountSnapshot:
        """Fetch current account state."""
        payload = self._request("GET", "/v2/account")
        return AccountSnapshot(
            account_number=payload["account_number"],
            equity=float(payload["equity"]),
            last_equity=float(payload["last_equity"]),
            cash=float(payload["cash"]),
            buying_power=float(payload["buying_power"]),
            status=payload["status"],
            trading_blocked=bool(payload["trading_blocked"]),
            taken_at=datetime.now().astimezone(),
        )

    def get_positions(self) -> dict[str, Position]:
        """Fetch open positions, keyed by symbol."""
        payload = self._request("GET", "/v2/positions") or []
        return {
            row["symbol"]: Position(
                symbol=row["symbol"],
                qty=float(row["qty"]),
                market_value=float(row["market_value"]),
                avg_entry_price=float(row["avg_entry_price"]),
                current_price=float(row["current_price"]),
                unrealised_pl=float(row["unrealized_pl"]),
            )
            for row in payload
        }

    def get_orders(
        self, status: str = "all", limit: int = 100, after: date | None = None
    ) -> list[dict[str, Any]]:
        """List orders, most recent first."""
        params: dict[str, Any] = {"status": status, "limit": limit,
                                  "direction": "desc"}
        if after is not None:
            params["after"] = after.isoformat()
        return self._request("GET", "/v2/orders", params=params) or []

    def get_last_prices(self, symbols: list[str]) -> dict[str, float]:
        """Fetch the latest trade price for each symbol.

        Note:
            Uses the market-data host and the IEX feed, which is what free and
            paper accounts receive. Symbols with no recent IEX print are
            omitted rather than defaulted, so a caller cannot silently size a
            position off a fabricated price.

        """
        response = self._session.get(
            "https://data.alpaca.markets/v2/stocks/trades/latest",
            params={"symbols": ",".join(symbols), "feed": "iex"},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        trades = response.json().get("trades", {})
        return {sym: float(row["p"]) for sym, row in trades.items() if "p" in row}

    # -- write -------------------------------------------------------------

    def submit_order(
        self,
        symbol: str,
        qty: float,
        side: OrderSide,
        order_type: str = "market",
        time_in_force: TimeInForce = "day",
        client_order_id: str | None = None,
        limit_price: float | None = None,
    ) -> OrderResult:
        """Submit one order to the paper account.

        Args:
            symbol: Ticker.
            qty: Share quantity. Must be positive; direction comes from ``side``.
            side: ``"buy"`` or ``"sell"``.
            order_type: ``"market"`` or ``"limit"``.
            time_in_force: ``"day"``, ``"gtc"``, ``"opg"`` (market-on-open), or
                ``"cls"``.
            client_order_id: Idempotency key. Supplying one makes a duplicate
                submission fail rather than double-trade, which matters when a
                scheduled job might run twice.
            limit_price: Required for limit orders.

        Returns:
            The submitted order's state.

        Raises:
            ValueError: If ``qty`` is not positive or a limit order lacks a price.

        """
        if qty <= 0:
            raise ValueError(
                f"qty must be positive (got {qty}); use side to set direction."
            )
        if order_type == "limit" and limit_price is None:
            raise ValueError("limit orders require limit_price.")

        body: dict[str, Any] = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
        }
        if client_order_id:
            body["client_order_id"] = client_order_id
        if limit_price is not None:
            body["limit_price"] = str(round(limit_price, 2))

        logger.info("Submitting PAPER order: %s %s %s", side, qty, symbol)
        payload = self._request("POST", "/v2/orders", json=body)

        return OrderResult(
            order_id=payload["id"],
            client_order_id=payload["client_order_id"],
            symbol=payload["symbol"],
            side=payload["side"],
            qty=float(payload["qty"]),
            order_type=payload["type"],
            time_in_force=payload["time_in_force"],
            status=payload["status"],
            submitted_at=payload["submitted_at"],
            filled_qty=float(payload.get("filled_qty") or 0.0),
            filled_avg_price=(
                float(payload["filled_avg_price"])
                if payload.get("filled_avg_price")
                else None
            ),
        )

    def get_order(self, order_id: str) -> dict[str, Any]:
        """Fetch one order by id, to check fill status after submission."""
        return self._request("GET", f"/v2/orders/{order_id}")

    def cancel_all_orders(self) -> None:
        """Cancel every open order. Used to clear stale state before a run."""
        self._request("DELETE", "/v2/orders")
