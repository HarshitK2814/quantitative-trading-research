"""Headlines from Yahoo Finance via yfinance (free, no key), one call per symbol."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
MAX_LEN = 200


def _yahoo_symbol(sym: str) -> str:
    return sym.replace("/", "-")


def _default_news(sym_yf: str) -> list[dict]:
    """Ticker.news, falling back to Search. yfinance can swallow bad responses
    and return [], so an empty Ticker result is retried via Search; if Search
    raises, the error propagates (fetch_headlines turns it into None)."""
    import yfinance as yf

    try:
        items = yf.Ticker(sym_yf).news
        if items:
            return items
    except Exception as exc:
        logger.warning("Ticker.news failed for %s: %r", sym_yf, exc)
    return yf.Search(sym_yf, news_count=10).news or []


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
