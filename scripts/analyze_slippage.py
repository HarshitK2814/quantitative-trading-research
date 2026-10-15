"""Measured execution cost from our own fills -> research/slippage_study.md.

    PYTHONPATH=. python scripts/analyze_slippage.py
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from src.ledger import load_fills, slippage_summary

OUT = Path("research/slippage_study.md")
ASSUMED_BPS = 10.0


def main() -> None:
    fills = load_fills()
    table = slippage_summary(fills).round(2)
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
- Caveats: paper fills are simulated and optimistic; ETF liquidity here is
  extreme; sample is a few weeks; heavy tails come mostly from reference-price
  staleness, not market impact. This is evidence about the cost assumption,
  not proof of it.
"""
    OUT.write_text(text, encoding="utf-8")
    print(text)
    pd.set_option("display.width", 200)


if __name__ == "__main__":
    main()
