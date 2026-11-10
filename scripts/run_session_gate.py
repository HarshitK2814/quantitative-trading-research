"""Run the pre-registered gate for S1-S3 and print pass/fail.

    PYTHONPATH=. python scripts/run_session_gate.py
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf

from src.intraday.prices import to_yf
from src.intraday.strategies import REGISTRY
from src.intraday.validate import backtest_returns, gate


def main() -> None:
    for spec in REGISTRY.values():
        yf_syms = [to_yf(s) for s in spec.symbols]
        raw = yf.download(yf_syms, start="2015-01-01", auto_adjust=True,
                          progress=False)["Close"]
        if isinstance(raw, pd.Series):
            raw = raw.to_frame(yf_syms[0])
        result = gate(backtest_returns(raw.dropna(how="all"), spec.signal_fn))
        print(spec.id, result)


if __name__ == "__main__":
    main()
