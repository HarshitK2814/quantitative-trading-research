"""Write reports/weekly/<first>_to_<last>.md from Alpaca account history and the session log.

    PYTHONPATH=. python scripts/weekly_report.py
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf

from src.broker import AlpacaPaperBroker
from src.config import PROJECT_ROOT, load_broker_config
from src.intraday.report import equity_from_history, render_report, summarize


def load_spy(start: pd.Timestamp) -> pd.Series:
    """SPY daily closes from `start`, as a Series. Raises if empty."""
    raw = yf.download("SPY", start=start, auto_adjust=True, progress=False)["Close"]
    if isinstance(raw, pd.DataFrame):
        raw = raw.iloc[:, 0]
    spy = raw.dropna().astype(float)
    if spy.empty:
        raise ValueError("SPY download returned no data")
    return spy


def count_orders(log_path) -> int:
    """Buy/sell rows in the session log. 0 if the file is missing, empty, or lacks 'side'."""
    if not log_path.exists():
        return 0
    try:
        trades = pd.read_csv(log_path)
    except pd.errors.EmptyDataError:
        return 0
    if trades.empty or "side" not in trades.columns:
        return 0
    return int(trades["side"].isin(["buy", "sell"]).sum())


def main() -> None:
    broker = AlpacaPaperBroker(load_broker_config())
    hist = broker._request("GET", "/v2/account/portfolio/history",
                           params={"period": "3M", "timeframe": "1D"})
    equity = equity_from_history(hist)

    spy = load_spy(equity.index[0])
    spy = spy.reindex(equity.index).ffill().dropna()
    equity = equity.loc[spy.index]
    if len(equity) < 2:
        raise ValueError("not enough overlapping account and SPY history")

    stats = summarize(equity, spy)
    n_trades = count_orders(PROJECT_ROOT / "portfolio" / "session_log.csv")
    first = equity.index[0].date().isoformat()
    last = equity.index[-1].date().isoformat()

    out = PROJECT_ROOT / "reports" / "weekly" / f"{first}_to_{last}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(stats, first, last, n_trades))
    print(out)


if __name__ == "__main__":
    main()
