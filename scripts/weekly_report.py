"""Write reports/weekly/<date>.md from Alpaca account history and the session log.

    PYTHONPATH=. python scripts/weekly_report.py
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import yfinance as yf

from src.broker import AlpacaPaperBroker
from src.config import PROJECT_ROOT, load_broker_config
from src.intraday.report import summarize


def main() -> None:
    broker = AlpacaPaperBroker(load_broker_config())
    hist = broker._request("GET", "/v2/account/portfolio/history",
                           params={"period": "3M", "timeframe": "1D"})
    idx = pd.to_datetime(hist["timestamp"], unit="s").normalize()
    equity = pd.Series(hist["equity"], index=idx).dropna()
    equity = equity[~equity.index.duplicated(keep="last")]
    spy = yf.download("SPY", start=equity.index[0], auto_adjust=True,
                      progress=False)["Close"].squeeze()
    spy = spy.reindex(equity.index).ffill().dropna()
    stats = summarize(equity.loc[spy.index], spy)

    log = PROJECT_ROOT / "portfolio" / "session_log.csv"
    trades = pd.read_csv(log) if log.exists() else pd.DataFrame()
    n_trades = int(trades["side"].isin(["buy", "sell"]).sum()) if len(trades) else 0
    today = datetime.now(UTC).date().isoformat()
    out = PROJECT_ROOT / "reports" / "weekly" / f"{today}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"# Session trader, week ending {today}\n\n"
        f"| Metric | Value |\n|---|---|\n"
        f"| Return | {stats['return']:.2%} |\n"
        f"| SPY buy-and-hold | {stats['bench_return']:.2%} |\n"
        f"| Max drawdown | {stats['max_drawdown']:.2%} |\n"
        f"| Sharpe (annualised) | {stats['sharpe']:.2f} |\n"
        f"| Trading days | {stats['days']} |\n"
        f"| Orders logged | {n_trades} |\n\n"
        "**Read with care:** under ~250 trading days a Sharpe ratio carries almost "
        "no information. Alpaca paper fills ignore slippage and market impact.\n"
    )
    print(out)


if __name__ == "__main__":
    main()
