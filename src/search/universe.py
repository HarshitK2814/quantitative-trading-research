"""Point-in-time S&P 500 universe and price panel (reduces survivorship bias)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
ETFS = ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY",
        "XLU", "XLB", "XLRE", "XLC", "VNQ", "GLD", "SLV", "TLT", "IEF", "SHY", "LQD",
        "HYG", "TIP", "DBC", "USO", "UUP", "EFA", "EEM", "VGK", "EWJ", "MTUM", "USMV",
        "QUAL", "VLUE", "SH", "PSQ", "SSO", "QLD", "SDS", "SQQQ", "TQQQ", "TMF"]
CRYPTO = ["BTC-USD", "ETH-USD"]
LEVERAGE = {"SSO": 2, "QLD": 2, "SDS": 2, "SQQQ": 3, "TQQQ": 3, "TMF": 3}


def _yf(sym: str) -> str:
    return str(sym).strip().replace(".", "-")


def sp500_membership(start="2007-01-01", read_html=pd.read_html, today=None) -> pd.DataFrame:
    tables = read_html(WIKI)
    current = {_yf(s) for s in tables[0]["Symbol"]}
    ch = tables[1].iloc[:, :6].copy()
    ch.columns = ["date", "added", "an", "removed", "rn", "reason"]
    ch["date"] = pd.to_datetime(ch["date"], errors="coerce")
    ch = ch.dropna(subset=["date"]).sort_values("date", ascending=False)
    days = pd.bdate_range(start, pd.Timestamp(today) if today else pd.Timestamp.today().normalize())
    members, snaps, j, rows = set(current), [], 0, list(ch.itertuples())
    for d in days[::-1]:
        while j < len(rows) and rows[j].date > d:
            if isinstance(rows[j].added, str) and rows[j].added.strip():
                members.discard(_yf(rows[j].added))
            if isinstance(rows[j].removed, str) and rows[j].removed.strip():
                members.add(_yf(rows[j].removed))
            j += 1
        snaps.append(frozenset(members))
    snaps.reverse()
    cols = sorted(set().union(*snaps))
    pos = {c: k for k, c in enumerate(cols)}
    data = np.zeros((len(days), len(cols)), dtype=bool)
    for r, s in enumerate(snaps):
        data[r, [pos[t] for t in s]] = True
    return pd.DataFrame(data, index=days, columns=cols)


def load_panel(tickers, start="2007-01-01", cache_dir=Path("data/search")):
    import yfinance as yf
    cache_dir.mkdir(parents=True, exist_ok=True)
    cpath, vpath = cache_dir / "close.parquet", cache_dir / "volume.parquet"
    today = pd.Timestamp.today().normalize()
    if cpath.exists() and (today - pd.Timestamp(cpath.stat().st_mtime, unit="s")).days < 1:
        return pd.read_parquet(cpath), pd.read_parquet(vpath)
    closes, vols = [], []
    for i in range(0, len(tickers), 100):
        d = yf.download(tickers[i:i + 100], start=start, auto_adjust=True,
                        progress=False, threads=True)
        closes.append(d["Close"])
        vols.append(d["Volume"])
    close = pd.concat(closes, axis=1).sort_index()
    vol = pd.concat(vols, axis=1).sort_index()
    close = close.loc[:, ~close.columns.duplicated()]
    vol = vol.loc[:, ~vol.columns.duplicated()]
    close.to_parquet(cpath)
    vol.to_parquet(vpath)
    return close, vol


def top_liquid(close, volume, members, n=150):
    dv = (close * volume).rolling(63, min_periods=20).median()
    dv = dv.where(members.reindex_like(dv).fillna(False).astype(bool))
    rank = dv.rank(axis=1, ascending=False)
    return (rank <= n).fillna(False)
