"""Point-in-time S&P 500 universe and price panel (reduces survivorship bias)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PIT_URL = "https://raw.githubusercontent.com/fja05680/sp500/master/sp500_ticker_start_end.csv"
ETFS = ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY",
        "XLU", "XLB", "XLRE", "XLC", "VNQ", "GLD", "SLV", "TLT", "IEF", "SHY", "LQD",
        "HYG", "TIP", "DBC", "USO", "UUP", "EFA", "EEM", "VGK", "EWJ", "MTUM", "USMV",
        "QUAL", "VLUE", "SH", "PSQ", "SSO", "QLD", "SDS", "SQQQ", "TQQQ", "TMF"]
CRYPTO = ["BTC-USD", "ETH-USD"]
LEVERAGE = {"SSO": 2, "QLD": 2, "SDS": 2, "SQQQ": 3, "TQQQ": 3, "TMF": 3}


def _yf(sym: str) -> str:
    return str(sym).strip().replace(".", "-")


def _fetch_intervals(url: str = PIT_URL) -> pd.DataFrame:
    """Ticker membership intervals (fja05680/sp500). Cached under data/search/."""
    import io

    import requests
    cache = Path("data/search/sp500_ticker_start_end.csv")
    if cache.exists() and (pd.Timestamp.today() - pd.Timestamp(cache.stat().st_mtime, unit="s")).days < 7:
        return pd.read_csv(cache)
    text = requests.get(url, timeout=30).text
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text)
    return pd.read_csv(io.StringIO(text))


def sp500_membership(start="2007-01-01", fetch=_fetch_intervals, today=None) -> pd.DataFrame:
    """Bool frame (business days x yfinance tickers): member on that day.

    end_date is the removal day (not a member from then on); blank = still a member.
    """
    iv = fetch()
    days = pd.bdate_range(start, pd.Timestamp(today) if today else pd.Timestamp.today().normalize())
    iv = iv.assign(ticker=iv["ticker"].map(_yf),
                   start_date=pd.to_datetime(iv["start_date"]),
                   end_date=pd.to_datetime(iv["end_date"]).fillna(days[-1] + pd.Timedelta(days=1)))
    iv = iv[iv["end_date"] > days[0]]
    cols = sorted(iv["ticker"].unique())
    pos = {c: k for k, c in enumerate(cols)}
    data = np.zeros((len(days), len(cols)), dtype=bool)
    for t, a, b in zip(iv["ticker"], iv["start_date"], iv["end_date"], strict=True):
        data[(days >= a) & (days < b), pos[t]] = True
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
