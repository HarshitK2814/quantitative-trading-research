"""Headlines from the Alpaca news API (free with paper keys)."""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)
NEWS_URL = "https://data.alpaca.markets/v1beta1/news"


def _api_symbol(sym: str) -> str:
    return sym.replace("/", "")


def fetch_headlines(
    symbols: list[str], key_id: str, secret: str, limit: int = 5, get=requests.get
) -> dict[str, list[str]]:
    """Return up to ``limit`` recent headlines per symbol. Errors give empty lists."""
    out: dict[str, list[str]] = {s: [] for s in symbols}
    try:
        resp = get(
            NEWS_URL,
            params={"symbols": ",".join(_api_symbol(s) for s in symbols),
                    "limit": 50, "sort": "desc"},
            headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret},
            timeout=20,
        )
        resp.raise_for_status()
        by_api = {_api_symbol(s): s for s in symbols}
        for item in resp.json().get("news", []):
            for api_sym in item.get("symbols", []):
                sym = by_api.get(api_sym)
                if sym and len(out[sym]) < limit:
                    out[sym].append(item["headline"])
    except Exception as exc:  # news is advisory; never crash a session
        logger.warning("news fetch failed: %s", exc)
    return out
