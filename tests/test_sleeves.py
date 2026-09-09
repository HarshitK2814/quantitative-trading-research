"""Tests for the multi-strategy sleeve combiner.

These run offline against synthetic price panels. No broker connection is
required or made.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.sleeves import Sleeve, combined_target_weights, validate_allocation


def _flat_signal(weight: float, symbols: list[str]) -> callable:
    """A trivial signal_fn returning a constant weight on every date."""

    def _fn(prices: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            weight, index=prices.index, columns=symbols
        )

    return _fn


def _prices(n_days: int = 5, symbols: tuple[str, ...] = ("A", "B", "C")) -> pd.DataFrame:
    idx = pd.bdate_range("2026-01-01", periods=n_days)
    rng = np.random.default_rng(0)
    data = 100.0 + rng.normal(size=(n_days, len(symbols))).cumsum(axis=0)
    return pd.DataFrame(data, index=idx, columns=list(symbols))


# ---------------------------------------------------------------------------
# validate_allocation
# ---------------------------------------------------------------------------


def test_validate_allocation_passes_under_full_commitment() -> None:
    sleeves = [
        Sleeve("s1", "H1", 0.5, _flat_signal(0.2, ["A"])),
        Sleeve("s2", "H2", 0.5, _flat_signal(0.2, ["B"])),
    ]
    validate_allocation(sleeves)  # must not raise


def test_validate_allocation_rejects_overcommitment() -> None:
    sleeves = [
        Sleeve("s1", "H1", 0.7, _flat_signal(0.2, ["A"])),
        Sleeve("s2", "H2", 0.5, _flat_signal(0.2, ["B"])),
    ]
    with pytest.raises(ValueError, match="1.0"):
        validate_allocation(sleeves)


def test_validate_allocation_ignores_inactive_sleeves() -> None:
    sleeves = [
        Sleeve("s1", "H1", 0.7, _flat_signal(0.2, ["A"])),
        Sleeve("s2", "H2", 0.7, _flat_signal(0.2, ["B"]), active=False),
    ]
    validate_allocation(sleeves)  # inactive sleeve's fraction doesn't count


def test_validate_allocation_rejects_short_capable_sleeves() -> None:
    """No sleeve may run short exposure until the risk engine supports it."""
    sleeves = [Sleeve("s1", "H6", 0.5, _flat_signal(0.2, ["A"]), allow_short=True)]
    with pytest.raises(ValueError, match="allow_short"):
        validate_allocation(sleeves)


# ---------------------------------------------------------------------------
# combined_target_weights
# ---------------------------------------------------------------------------


def test_single_active_sleeve_is_scaled_by_its_fraction() -> None:
    prices = _prices()
    sleeve = Sleeve("s1", "H1", 0.6, _flat_signal(0.5, ["A", "B"]))
    combined, per_sleeve = combined_target_weights([sleeve], prices)
    assert combined["A"] == pytest.approx(0.3)  # 0.5 * 0.6
    assert combined["B"] == pytest.approx(0.3)
    assert per_sleeve["s1"]["A"] == pytest.approx(0.5)  # unscaled, own weight


def test_two_sleeves_on_disjoint_symbols_both_contribute() -> None:
    prices = _prices()
    sleeves = [
        Sleeve("s1", "H1", 0.5, _flat_signal(1.0, ["A"])),
        Sleeve("s2", "H2", 0.5, _flat_signal(1.0, ["B"])),
    ]
    combined, _ = combined_target_weights(sleeves, prices)
    assert combined["A"] == pytest.approx(0.5)
    assert combined["B"] == pytest.approx(0.5)


def test_two_sleeves_on_the_same_symbol_sum() -> None:
    prices = _prices()
    sleeves = [
        Sleeve("s1", "H1", 0.5, _flat_signal(0.4, ["A"])),
        Sleeve("s2", "H2", 0.5, _flat_signal(0.4, ["A"])),
    ]
    combined, _ = combined_target_weights(sleeves, prices)
    assert combined["A"] == pytest.approx(0.4)  # (0.4*0.5) + (0.4*0.5)


def test_inactive_sleeve_contributes_nothing() -> None:
    prices = _prices()
    sleeves = [
        Sleeve("s1", "H1", 1.0, _flat_signal(0.5, ["A"])),
        Sleeve("s2", "H2", 0.0, _flat_signal(99.0, ["A"]), active=False),
    ]
    combined, per_sleeve = combined_target_weights(sleeves, prices)
    assert combined["A"] == pytest.approx(0.5)
    assert "s2" not in per_sleeve


def test_empty_sleeve_list_returns_empty_series() -> None:
    combined, per_sleeve = combined_target_weights([], _prices())
    assert combined.empty
    assert per_sleeve == {}


def test_uses_only_the_latest_available_date() -> None:
    """A sleeve's weight history may extend beyond what's usable; only the
    most recent non-empty row should ever reach the combined vector."""
    prices = _prices(n_days=10)

    def growing_signal(p: pd.DataFrame) -> pd.DataFrame:
        # Weight ramps by row index -- only the last row's value should show.
        return pd.DataFrame(
            {"A": np.arange(len(p)) * 0.01}, index=p.index
        )

    sleeve = Sleeve("s1", "H1", 1.0, growing_signal)
    combined, per_sleeve = combined_target_weights([sleeve], prices)
    assert combined["A"] == pytest.approx((len(prices) - 1) * 0.01)
