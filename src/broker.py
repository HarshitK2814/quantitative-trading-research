"""Alpaca **paper** broker client.

Every method here routes through :func:`src.config.load_broker_config`, which
refuses to return credentials unless the endpoint is the paper endpoint and
``PAPER_TRADING_ONLY`` is true. There is no code path in this module that can
reach a live-money account.

Design notes
------------
A thin REST wrapper is used rather than ``alpaca-py``. The reasons are specific
rather than dogmatic:

* The project needs exactly a handful of operations (clock, account,
  positions, submit, list orders, and -- for H9's options hedge -- option
  contract lookup, option quotes, and option order submission). A dependency
  is not warranted for that.
* Every request goes through :meth:`AlpacaPaperBroker._request`, which is a
  single auditable place to enforce the paper endpoint at call time -- not just
  at construction time.
* Fewer moving parts between the research and the order.

``alpaca-py`` remains the right choice for anything needing streaming, complex
order types, or the full asset universe.

Options support
----------------
The option methods below were verified against the real paper API before
being written -- contract listing, quote format, and order schema (including
``position_intent``, which options orders require and equity orders do not)
were each probed live and a real (immediately cancelled) test order was
submitted to confirm the schema, rather than being guessed from
documentation. See ``research/daily_log.md`` for that verification.
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
    #: Options trading level Alpaca has approved for this paper account
    #: (0 = not approved). Defaulted so existing callers/tests that build an
    #: AccountSnapshot without options fields keep working unchanged.
    options_approved_level: int = 0
    options_buying_power: float = 0.0


@dataclass(frozen=True)
class OptionContract:
    """One listed option contract, as returned by the contracts endpoint."""

    symbol: str  # OCC symbol, e.g. "SPY261002P00725000"
    underlying_symbol: str
    option_type: str  # "put" or "call"
    strike_price: float
    expiration_date: date
    tradable: bool


@dataclass(frozen=True)
class OptionQuote:
    """Latest bid/ask for one option contract."""

    symbol: str
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        """Midpoint of bid and ask -- the estimate used for cost planning."""
        return (self.bid + self.ask) / 2.0


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
            options_approved_level=int(payload.get("options_approved_level") or 0),
            options_buying_power=float(payload.get("options_buying_power") or 0.0),
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

    # -- options (H9) --------------------------------------------------------

    def get_option_contracts(
        self,
        underlying_symbol: str,
        option_type: Literal["put", "call"],
        expiration_gte: date,
        expiration_lte: date,
        strike_gte: float | None = None,
        strike_lte: float | None = None,
        limit: int = 100,
    ) -> list[OptionContract]:
        """List active, tradable option contracts matching the given filters.

        Args:
            underlying_symbol: e.g. ``"SPY"``.
            option_type: ``"put"`` or ``"call"``.
            expiration_gte: Earliest acceptable expiration date, inclusive.
            expiration_lte: Latest acceptable expiration date, inclusive.
            strike_gte: Optional minimum strike.
            strike_lte: Optional maximum strike.
            limit: Maximum contracts to return.

        Returns:
            Matching contracts with ``tradable=False`` rows already excluded.

        """
        params: dict[str, Any] = {
            "underlying_symbols": underlying_symbol,
            "status": "active",
            "type": option_type,
            "expiration_date_gte": expiration_gte.isoformat(),
            "expiration_date_lte": expiration_lte.isoformat(),
            "limit": limit,
        }
        if strike_gte is not None:
            params["strike_price_gte"] = str(strike_gte)
        if strike_lte is not None:
            params["strike_price_lte"] = str(strike_lte)

        payload = self._request("GET", "/v2/options/contracts", params=params) or {}
        contracts = []
        for row in payload.get("option_contracts", []):
            if not row.get("tradable"):
                continue
            contracts.append(
                OptionContract(
                    symbol=row["symbol"],
                    underlying_symbol=row["underlying_symbol"],
                    option_type=row["type"],
                    strike_price=float(row["strike_price"]),
                    expiration_date=date.fromisoformat(row["expiration_date"]),
                    tradable=bool(row["tradable"]),
                )
            )
        return contracts

    def get_option_quotes(self, symbols: list[str]) -> dict[str, OptionQuote]:
        """Fetch the latest bid/ask for one or more option contracts.

        Note:
            Uses the options market-data host and a different response shape
            (``bp``/``ap`` for bid/ask price) from :meth:`get_last_prices`'s
            equity trades endpoint -- they are genuinely different APIs, not
            a naming inconsistency.

        """
        if not symbols:
            return {}
        response = self._session.get(
            "https://data.alpaca.markets/v1beta1/options/quotes/latest",
            params={"symbols": ",".join(symbols)},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        quotes = response.json().get("quotes", {})
        return {
            sym: OptionQuote(symbol=sym, bid=float(row["bp"]), ask=float(row["ap"]))
            for sym, row in quotes.items()
            if "bp" in row and "ap" in row
        }

    def get_option_positions(self) -> dict[str, Position]:
        """Fetch open option positions, keyed by OCC symbol.

        Note:
            Reuses the equity :class:`Position` shape -- Alpaca returns
            option positions through the same ``/v2/positions`` endpoint with
            the same fields, ``qty`` denominated in contracts rather than
            shares. Filtered to ``asset_class == "us_option"`` so equity
            positions in the same response aren't picked up here.

        """
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
            if row.get("asset_class") == "us_option"
        }

    def submit_option_order(
        self,
        symbol: str,
        qty: int,
        side: OrderSide,
        position_intent: Literal[
            "buy_to_open", "buy_to_close", "sell_to_open", "sell_to_close"
        ],
        order_type: str = "limit",
        limit_price: float | None = None,
        time_in_force: TimeInForce = "day",
        client_order_id: str | None = None,
    ) -> OrderResult:
        """Submit one options order to the paper account.

        Note:
            Option prices are quoted **per share**; the actual dollar cost of
            one contract is ``price * 100`` (the standard multiplier), not
            ``price``. Callers must apply that multiplier themselves when
            sizing or logging cost -- this method does not, so it stays a
            faithful mirror of what the API actually charges per unit.

        Args:
            symbol: OCC option symbol.
            qty: Number of contracts. Must be positive.
            side: ``"buy"`` or ``"sell"``.
            position_intent: Required by Alpaca for options (unlike equities)
                to disambiguate opening from closing a position.
            order_type: ``"market"`` or ``"limit"``.
            limit_price: Required for limit orders (per share, not per
                contract).
            time_in_force: As for equity orders.
            client_order_id: Idempotency key.

        Returns:
            The submitted order's state.

        """
        if qty <= 0:
            raise ValueError(f"qty must be positive (got {qty}).")
        if order_type == "limit" and limit_price is None:
            raise ValueError("limit orders require limit_price.")

        body: dict[str, Any] = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
            "position_intent": position_intent,
        }
        if client_order_id:
            body["client_order_id"] = client_order_id
        if limit_price is not None:
            body["limit_price"] = str(round(limit_price, 2))

        logger.info(
            "Submitting PAPER option order: %s %s %s (%s)",
            side, qty, symbol, position_intent,
        )
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
