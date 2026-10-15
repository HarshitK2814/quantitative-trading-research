"""Tests for the trade-ledger readers. Offline; synthetic CSVs only."""

from __future__ import annotations

import pandas as pd
import pytest

from src.ledger import load_fills, slippage_summary

COLS = [
    "timestamp_utc", "trade_date", "strategy_version", "symbol", "side", "qty",
    "order_type", "time_in_force", "reference_price", "filled_avg_price",
    "filled_qty", "slippage_bps", "notional", "current_weight", "target_weight",
    "weight_delta", "reason", "order_id", "client_order_id", "status",
    "account_equity", "dry_run",
]


def _row(order_id, status, slip, side="buy", notional=10_000.0, dry=False):
    base = dict.fromkeys(COLS, "")
    base.update(
        timestamp_utc="2026-10-01T16:00:00+00:00", trade_date="2026-10-01",
        symbol="XLF", side=side, order_id=order_id, status=status,
        slippage_bps=slip, notional=notional, dry_run=dry,
    )
    return base


def _write(tmp_path, rows):
    path = tmp_path / "trades.csv"
    pd.DataFrame(rows, columns=COLS).to_csv(path, index=False)
    return path


def test_load_fills_keeps_only_filled_nondry_with_slippage(tmp_path) -> None:
    path = _write(tmp_path, [
        _row("a", "pending_new", ""),
        _row("a", "filled", 2.0),
        _row("b", "filled", "", dry=False),      # no slippage -> dropped
        _row("c", "DRY_RUN", 1.0, dry=True),     # dry run -> dropped
        _row("d", "accepted", ""),
    ])
    fills = load_fills(path)
    assert list(fills["order_id"]) == ["a"]
    assert fills["slippage_bps"].iloc[0] == pytest.approx(2.0)


def test_load_fills_dedupes_by_order_id_keeping_last(tmp_path) -> None:
    path = _write(tmp_path, [_row("a", "filled", 1.0), _row("a", "filled", 3.0)])
    fills = load_fills(path)
    assert len(fills) == 1
    assert fills["slippage_bps"].iloc[0] == pytest.approx(3.0)


def test_slippage_summary_statistics(tmp_path) -> None:
    rows = [_row(str(i), "filled", s, side="buy" if i % 2 == 0 else "sell")
            for i, s in enumerate([0.0, 2.0, 4.0, -2.0, 20.0, 0.0])]
    fills = load_fills(_write(tmp_path, rows))
    table = slippage_summary(fills)
    overall = table.loc["all"]
    assert overall["n"] == 6
    assert overall["mean_bps"] == pytest.approx(4.0)
    assert overall["median_bps"] == pytest.approx(1.0)
    assert overall["share_over_10bps"] == pytest.approx(1 / 6)
    assert {"all", "buy", "sell"} <= set(table.index)


def test_slippage_summary_empty_is_safe(tmp_path) -> None:
    fills = load_fills(_write(tmp_path, [_row("a", "pending_new", "")]))
    assert slippage_summary(fills).loc["all", "n"] == 0
