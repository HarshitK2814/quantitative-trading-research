"""Headlines from Yahoo Finance via yfinance (free, no key), one call per symbol."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
MAX_LEN = 200


def _yahoo_symbol(sym: str) -> str:
    return sym.replace("/", "-")


def _default_news(sym_yf: str) -> list[dict]:
    import yfinance as yf

    try:
        return yf.Ticker(sym_yf).news
    except Exception:
        # yfinance 0.2.65: Ticker.news endpoint returns "Yahoo is down"; search works.
        return yf.Search(sym_yf, news_count=10).news


def _title(item) -> str | None:
    if not isinstance(item, dict):
        return None
    content = item.get("content")
    title = content.get("title") if isinstance(content, dict) else None
    title = title or item.get("title")
    if not isinstance(title, str):
        return None
    clean = " ".join(title.split())[:MAX_LEN]
    return clean or None


def fetch_headlines(
    symbols: list[str], limit: int = 5, ticker_news=None
) -> dict[str, list[str] | None]:
    """Up to ``limit`` headlines per symbol. ``None`` means that fetch failed."""
    getter = ticker_news or _default_news
    out: dict[str, list[str] | None] = {}
    for sym in symbols:
        try:
            titles = [t for t in (_title(i) for i in (getter(_yahoo_symbol(sym)) or []))
                      if t]
            out[sym] = titles[:limit]
        except Exception as exc:  # advisory; never crash a session
            logger.warning("news fetch failed for %s: %s", sym, type(exc).__name__)
            out[sym] = None
    return out
