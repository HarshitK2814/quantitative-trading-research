"""Tests for the risk engine and order generation.

These run offline. No broker connection is required or made.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.broker import Position
from src.config import RiskLimits
from src.execution import compute_slippage_bps, estimate_turnover, plan_orders
from src.risk import check_and_adjust, current_drawdown, exposure_report

LIMITS = RiskLimits()


def _position(symbol: str, qty: float, price: float) -> Position:
    return Position(
        symbol=symbol, qty=qty, market_value=qty * price,
        avg_entry_price=price, current_price=price, unrealised_pl=0.0,
    )


# ---------------------------------------------------------------------------
# Risk engine
# ---------------------------------------------------------------------------


def test_compliant_weights_pass_untouched() -> None:
    weights = pd.Series({"SPY": 0.2, "TLT": 0.2, "GLD": 0.2})
    report = check_and_adjust(weights)
    assert report.ok
    assert report.breaches == []
    pd.testing.assert_series_equal(report.adjusted, weights)


def test_per_asset_cap_binds() -> None:
    weights = pd.Series({"SPY": 0.60, "TLT": 0.20})
    report = check_and_adjust(weights)
    assert report.adjusted["SPY"] == pytest.approx(LIMITS.max_single_weight)
    assert any("Per-asset cap" in b for b in report.breaches)


def test_negative_weights_are_zeroed() -> None:
    """The system is long-only; a short request must not become an order."""
    weights = pd.Series({"SPY": 0.3, "TLT": -0.2})
    report = check_and_adjust(weights)
    assert report.adjusted["TLT"] == 0.0
    assert any("long-only" in b for b in report.breaches)


def test_asset_class_cap_scales_proportionally() -> None:
    """Class exposure is scaled down, preserving relative preferences.

    Dropping names instead would discard the strategy's ranking; scaling keeps
    it while respecting the limit.
    """
    weights = pd.Series(
        {"SPY": 0.25, "QQQ": 0.25, "IWM": 0.20, "DIA": 0.10}  # all equity_broad
    )
    report = check_and_adjust(weights)
    total = report.adjusted[["SPY", "QQQ", "IWM", "DIA"]].sum()
    assert total == pytest.approx(LIMITS.max_asset_class_weight)
    # SPY and QQQ were equal before; they must remain equal after.
    assert report.adjusted["SPY"] == pytest.approx(report.adjusted["QQQ"])
    assert report.adjusted["SPY"] > report.adjusted["DIA"]


def test_gross_exposure_cap_binds() -> None:
    weights = pd.Series({"SPY": 0.25, "TLT": 0.25, "GLD": 0.25, "VNQ": 0.25,
                         "SLV": 0.25})
    report = check_and_adjust(weights)
    assert report.gross_exposure <= LIMITS.max_gross_exposure + 1e-9


def test_risk_engine_never_increases_exposure() -> None:
    """The engine's core invariant: it may only ever reduce risk."""
    for weights in (
        pd.Series({"SPY": 0.1, "TLT": 0.1}),
        pd.Series({"SPY": 0.9}),
        pd.Series({"SPY": 0.3, "QQQ": 0.3, "IWM": 0.3, "DIA": 0.3}),
        pd.Series({"SPY": -0.5, "TLT": 0.2}),
    ):
        report = check_and_adjust(weights)
        assert report.adjusted.sum() <= max(weights.clip(lower=0).sum(), 0) + 1e-9
        assert (report.adjusted >= -1e-12).all()


def test_drawdown_derisk_halves_exposure() -> None:
    equity = pd.Series([100.0, 120.0, 100.0])  # -16.7% from peak
    report = check_and_adjust(pd.Series({"SPY": 0.2, "TLT": 0.2}),
                              equity_history=equity)
    assert report.adjusted.sum() == pytest.approx(0.2)  # halved from 0.4
    assert any("DE-RISK" in b for b in report.breaches)
    assert not report.halted


def test_drawdown_halt_removes_all_exposure() -> None:
    equity = pd.Series([100.0, 120.0, 85.0])  # -29.2% from peak
    report = check_and_adjust(pd.Series({"SPY": 0.2, "TLT": 0.2}),
                              equity_history=equity)
    assert report.adjusted.sum() == pytest.approx(0.0)
    assert report.halted
    assert any("HALT" in b for b in report.breaches)


def test_no_drawdown_at_a_new_high() -> None:
    assert current_drawdown(pd.Series([100.0, 110.0, 120.0])) == pytest.approx(0.0)


def test_current_drawdown_handles_empty_history() -> None:
    assert current_drawdown(pd.Series([], dtype=float)) == 0.0


def test_exposure_report_totals() -> None:
    values = pd.Series({"SPY": 20000.0, "TLT": 20000.0, "GLD": 10000.0})
    report = exposure_report(values, equity=100000.0)
    assert report["gross_exposure"] == pytest.approx(0.5)
    assert report["cash_weight"] == pytest.approx(0.5)
    assert report["n_positions"] == 3
    assert report["class_bond"] == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# Order generation
# ---------------------------------------------------------------------------


def test_orders_from_flat_book() -> None:
    orders = plan_orders(
        pd.Series({"SPY": 0.5, "TLT": 0.5}), {}, 100_000.0,
        {"SPY": 100.0, "TLT": 50.0},
    )
    by_symbol = {o.symbol: o for o in orders}
    assert by_symbol["SPY"].side == "buy"
    assert by_symbol["SPY"].qty == 500
    assert by_symbol["TLT"].qty == 1000


def test_no_orders_when_already_at_target() -> None:
    positions = {"SPY": _position("SPY", 500, 100.0)}
    orders = plan_orders(
        pd.Series({"SPY": 0.5}), positions, 100_000.0, {"SPY": 100.0}
    )
    assert orders == []


def test_exit_generates_a_full_sell() -> None:
    """A symbol dropping out of the target must be sold entirely."""
    positions = {"XLE": _position("XLE", 300, 60.0)}
    orders = plan_orders(
        pd.Series({"SPY": 0.5}), positions, 100_000.0,
        {"SPY": 100.0, "XLE": 60.0},
    )
    sells = [o for o in orders if o.side == "sell"]
    assert len(sells) == 1
    assert sells[0].symbol == "XLE"
    assert sells[0].qty == 300


def test_sells_are_ordered_before_buys() -> None:
    """Proceeds must be freed before purchases, or buying power can fail."""
    positions = {"XLE": _position("XLE", 300, 60.0)}
    orders = plan_orders(
        pd.Series({"SPY": 0.5}), positions, 100_000.0,
        {"SPY": 100.0, "XLE": 60.0},
    )
    sides = [o.side for o in orders]
    assert sides.index("sell") < sides.index("buy")


def test_dust_trades_are_suppressed() -> None:
    """Tiny rebalancing trades cost more than they correct."""
    positions = {"SPY": _position("SPY", 500, 100.0)}
    orders = plan_orders(
        pd.Series({"SPY": 0.5001}), positions, 100_000.0, {"SPY": 100.0},
        min_notional=50.0,
    )
    assert orders == []


def test_rounding_never_increases_exposure() -> None:
    """Whole-share quantities round toward zero, so we never overshoot."""
    orders = plan_orders(
        pd.Series({"SPY": 0.5}), {}, 100_000.0, {"SPY": 777.0}
    )
    assert orders[0].qty == 64  # floor(50000/777) = 64, not 65
    assert orders[0].qty * 777.0 <= 50_000.0


def test_missing_price_skips_rather_than_guesses() -> None:
    """A position must never be sized off a fabricated price."""
    orders = plan_orders(pd.Series({"SPY": 0.5}), {}, 100_000.0, {})
    assert orders == []


def test_zero_equity_produces_no_orders() -> None:
    assert plan_orders(pd.Series({"SPY": 0.5}), {}, 0.0, {"SPY": 100.0}) == []


def test_estimate_turnover() -> None:
    orders = plan_orders(
        pd.Series({"SPY": 0.5, "TLT": 0.5}), {}, 100_000.0,
        {"SPY": 100.0, "TLT": 50.0},
    )
    assert estimate_turnover(orders, 100_000.0) == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# Slippage
# ---------------------------------------------------------------------------


def test_slippage_sign_convention() -> None:
    """Positive slippage always means the fill was worse than the reference."""
    assert compute_slippage_bps(100.0, 100.10, "buy") == pytest.approx(10.0)
    assert compute_slippage_bps(100.0, 99.90, "buy") == pytest.approx(-10.0)
    assert compute_slippage_bps(100.0, 99.90, "sell") == pytest.approx(10.0)
    assert compute_slippage_bps(100.0, 100.10, "sell") == pytest.approx(-10.0)


def test_slippage_is_none_without_a_fill() -> None:
    assert compute_slippage_bps(100.0, None, "buy") is None
    assert compute_slippage_bps(0.0, 100.0, "buy") is None
