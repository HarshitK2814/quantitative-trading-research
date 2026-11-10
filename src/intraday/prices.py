"""Price helpers: daily bars from Yahoo, crypto last trade from Alpaca."""

from __future__ import annotations

import pandas as pd
import requests
import yfinance as yf

CRYPTO_LATEST = "https://data.alpaca.markets/v1beta3/crypto/us/latest/trades"


def to_yf(sym: str) -> str:
    """Alpaca symbol -> Yahoo symbol (BTC/USD -> BTC-USD)."""
    return sym.replace("/", "-")


def load_daily_closes(symbols: list[str], start: str = "2023-01-01") -> dict[str, pd.Series]:
    """Daily adjusted closes keyed by Alpaca symbol."""
    out: dict[str, pd.Series] = {}
    raw = yf.download([to_yf(s) for s in symbols], start=start, auto_adjust=True,
                      progress=False)["Close"]
    if isinstance(raw, pd.Series):
        raw = raw.to_frame(to_yf(symbols[0]))
    for s in symbols:
        col = to_yf(s)
        if col in raw.columns:
            out[s] = raw[col].dropna()
    return out


def crypto_last_prices(symbols, key_id, secret, get=requests.get) -> dict[str, float]:
    """Latest crypto trade price per Alpaca symbol. Errors give an empty dict."""
    if not symbols:
        return {}
    try:
        r = get(CRYPTO_LATEST, params={"symbols": ",".join(symbols)},
                headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret},
                timeout=20)
        r.raise_for_status()
        return {s: float(t["p"]) for s, t in r.json().get("trades", {}).items()}
    except Exception:
        return {}
