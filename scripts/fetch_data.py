"""Week-2 data pipeline check: download, validate, and cross-check the panel."""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from src.config import SPLITS, UNIVERSE
from src.data import (
    common_history_start,
    load_prices,
    validate_panel,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 50)

START = SPLITS.history_start
END = date.today()

print("=" * 78)
print("PRIMARY VENDOR: yfinance")
print("=" * 78)
yf_panel = load_prices(UNIVERSE, START, END, vendor="yfinance")
report = validate_panel(yf_panel)
print(report.summary())
print()
print("First valid observation per ticker:")
for ticker, first in report.first_valid.items():
    print(f"  {ticker:<5} {first}")
print()
print(f"Common history starts: {common_history_start(yf_panel).date()}")
print()
print(yf_panel.tail(3).round(2).to_string())
