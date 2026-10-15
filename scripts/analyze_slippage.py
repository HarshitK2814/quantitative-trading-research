"""Measured execution cost from our own fills -> research/slippage_study.md.

    PYTHONPATH=. python scripts/analyze_slippage.py
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from src.execution import TRADES_PATH
from src.ledger import load_fills, slippage_summary

OUT = Path(__file__).resolve().parents[1] / "research" / "slippage_study.md"
ASSUMED_BPS = 10.0


def main() -> None:
    fills = load_fills()
    raw = pd.read_csv(TRADES_PATH)
    raw_dry = raw["dry_run"].astype(str).str.lower().eq("true")
    raw_filled = int((raw["status"].eq("filled")
                      & pd.to_numeric(raw["slippage_bps"], errors="coerce").notna()
                      & ~raw_dry).sum())
    table = slippage_summary(fills)
    table["share_over_10bps_pct"] = (100 * table.pop("share_over_10bps")).round(1)
    table = table.round(2)
    overall = table.loc["all"]
    trimmed = fills["slippage_bps"].clip(
        fills["slippage_bps"].quantile(0.05), fills["slippage_bps"].quantile(0.95)
    ).mean()
    text = f"""# Measured slippage from the live ledger

**Generated:** {date.today()} from `portfolio/trades.csv` (read-only).
**Sign:** positive = worse for us. **Definition:** implementation shortfall vs the
reference price at order generation (includes drift until fill), not pure spread.

{table.to_markdown()}

- Fills analysed: **{int(overall['n'])}**
- Mean {overall['mean_bps']:.2f} bps, median {overall['median_bps']:.2f} bps,
  5%-winsorised mean {trimmed:.2f} bps. Backtest headline assumption:
  **{ASSUMED_BPS:.0f} bps** per unit turnover.
- Dedup: {raw_filled} raw filled rows were reduced to one row per order_id
  ({int(overall['n'])} orders); the duplicates are repeated re-logs from the
  2026-09-09 re-runs.
- Caveats: paper fills are simulated and optimistic; ETF liquidity here is
  extreme; sample is a few weeks. Heavy tails may reflect price drift between
  order generation and fill; this analysis does not separate drift from market
  impact (hypothesis, not tested here). This is evidence about the cost
  assumption, not proof of it.
"""
    OUT.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
