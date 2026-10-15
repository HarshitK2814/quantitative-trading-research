"""Read-only analysis of the trade journal.

``portfolio/trades.csv`` is append-only evidence. This module only reads it.

Slippage here is signed so that **positive is worse for us**, measured against
the reference price at order generation. Because fills can occur a session
later, it is *implementation shortfall* (spread + impact + price drift), not
pure spread. Its use is to sanity-check the 10 bps backtest cost assumption.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.execution import TRADES_PATH

# pd.cut is right-inclusive: a notional of exactly 5_000 falls in "<5k" and
# exactly 20_000 falls in "5k-20k".
_NOTIONAL_BINS = [0.0, 5_000.0, 20_000.0, np.inf]
_NOTIONAL_LABELS = ["<5k", "5k-20k", ">20k"]


def load_fills(path: Path = TRADES_PATH) -> pd.DataFrame:
    """Return one row per filled, non-dry-run order that has a slippage figure."""
    frame = pd.read_csv(path)
    frame["slippage_bps"] = pd.to_numeric(frame["slippage_bps"], errors="coerce")
    frame["notional"] = pd.to_numeric(frame["notional"], errors="coerce")
    dry = frame["dry_run"].astype(str).str.lower().eq("true")
    mask = frame["status"].eq("filled") & frame["slippage_bps"].notna() & ~dry
    fills = frame.loc[mask].drop_duplicates("order_id", keep="last")
    return fills.reset_index(drop=True)


def _stats(values: pd.Series) -> dict[str, float]:
    """Summary statistics for a series of slippage values in bps.

    Returns n, mean, median, p90 of absolute value, sample std (ddof=1) and
    the share of values strictly above 10 bps. Empty input gives n=0 and NaNs.
    """
    if values.empty:
        return {"n": 0, "mean_bps": np.nan, "median_bps": np.nan,
                "p90_abs_bps": np.nan, "std_bps": np.nan,
                "share_over_10bps": np.nan}
    return {
        "n": int(values.size),
        "mean_bps": float(values.mean()),
        "median_bps": float(values.median()),
        "p90_abs_bps": float(values.abs().quantile(0.9)),
        "std_bps": float(values.std(ddof=1)) if values.size > 1 else np.nan,
        "share_over_10bps": float((values > 10.0).mean()),
    }


def slippage_summary(fills: pd.DataFrame) -> pd.DataFrame:
    """Summarise slippage overall, by side, and by order-size bucket."""
    groups: dict[str, pd.Series] = {"all": fills["slippage_bps"]}
    for side, sub in fills.groupby("side"):
        groups[str(side)] = sub["slippage_bps"]
    if not fills.empty:
        buckets = pd.cut(fills["notional"], _NOTIONAL_BINS, labels=_NOTIONAL_LABELS)
        for label in _NOTIONAL_LABELS:
            groups[f"notional {label}"] = fills.loc[buckets == label, "slippage_bps"]
    return pd.DataFrame({k: _stats(v) for k, v in groups.items()}).T
