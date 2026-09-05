"""Tests for the data layer.

These run offline against synthetic panels. Network-dependent checks live in
``scripts/fetch_data.py`` so that the test suite stays deterministic and fast:
a suite that fails when Yahoo is slow trains you to ignore failures.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data import (
    common_history_start,
    compare_vendors,
    to_returns,
    validate_panel,
)


@pytest.fixture
def clean_panel() -> pd.DataFrame:
    """A well-formed 3-ticker panel over 100 business days."""
    index = pd.bdate_range("2020-01-01", periods=100, name="date")
    rng = np.random.default_rng(42)
    data = {
        ticker: 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(index))))
        for ticker in ("AAA", "BBB", "CCC")
    }
    return pd.DataFrame(data, index=index)


def test_clean_panel_validates(clean_panel: pd.DataFrame) -> None:
    report = validate_panel(clean_panel)
    assert report.ok
    assert report.errors == []
    assert report.n_rows == 100
    assert report.n_cols == 3
    assert all(count == 0 for count in report.missing_counts.values())


def test_unsorted_index_is_an_error(clean_panel: pd.DataFrame) -> None:
    shuffled = clean_panel.iloc[::-1]
    report = validate_panel(shuffled)
    assert not report.ok
    assert any("sorted" in e for e in report.errors)


def test_duplicate_dates_are_an_error(clean_panel: pd.DataFrame) -> None:
    duplicated = pd.concat([clean_panel, clean_panel.iloc[[5]]]).sort_index()
    report = validate_panel(duplicated)
    assert not report.ok
    assert any("Duplicated" in e for e in report.errors)


def test_non_positive_prices_are_an_error(clean_panel: pd.DataFrame) -> None:
    broken = clean_panel.copy()
    broken.iloc[10, 0] = 0.0
    report = validate_panel(broken)
    assert not report.ok
    assert any("Non-positive" in e for e in report.errors)


def test_extreme_moves_are_flagged_not_removed(clean_panel: pd.DataFrame) -> None:
    """Outliers are reported for inspection; the data is left untouched.

    A 25% ETF move can be real (March 2020) or a bad print. Only inspection
    distinguishes them, so automatic removal would silently discard real
    events.
    """
    spiked = clean_panel.copy()
    spiked.iloc[50, 0] = spiked.iloc[49, 0] * 1.35
    report = validate_panel(spiked, outlier_threshold=0.20)
    assert report.ok  # a spike is not a structural error
    assert any(ticker == "AAA" for _, ticker, _ in report.extreme_moves)
    assert spiked.iloc[50, 0] == pytest.approx(clean_panel.iloc[49, 0] * 1.35)


def test_missing_before_first_listing_is_not_counted_as_missing(
    clean_panel: pd.DataFrame,
) -> None:
    """Nulls before an asset's inception are expected, not data loss."""
    late = clean_panel.copy()
    late.iloc[:30, 2] = np.nan  # CCC lists 30 days in
    report = validate_panel(late)
    assert report.missing_counts["CCC"] == 0
    assert report.first_valid["CCC"] == str(late.index[30].date())


def test_interior_missing_is_counted(clean_panel: pd.DataFrame) -> None:
    """A hole after listing is genuine missing data and must be surfaced."""
    holed = clean_panel.copy()
    holed.iloc[40:45, 1] = np.nan
    report = validate_panel(holed)
    assert report.missing_counts["BBB"] == 5


def test_calendar_gaps_detected(clean_panel: pd.DataFrame) -> None:
    gapped = pd.concat([clean_panel.iloc[:20], clean_panel.iloc[60:]])
    report = validate_panel(gapped, max_gap_days=5)
    assert report.calendar_gaps


def test_to_returns_does_not_fabricate_zeros(clean_panel: pd.DataFrame) -> None:
    """A missing price must yield a missing return, never a filled zero.

    A forward-filled zero return is a fabricated observation. Fabricated zeros
    understate volatility and therefore inflate every Sharpe ratio downstream.
    """
    holed = clean_panel.copy()
    holed.iloc[40:45, 1] = np.nan
    returns = to_returns(holed)
    assert returns["BBB"].iloc[40:45].isna().all()
    assert not (returns["BBB"].iloc[40:45] == 0).any()


def test_common_history_start_is_the_latest_first_valid(
    clean_panel: pd.DataFrame,
) -> None:
    """Cross-sectional ranking needs every asset present."""
    staggered = clean_panel.copy()
    staggered.iloc[:10, 0] = np.nan
    staggered.iloc[:25, 1] = np.nan
    assert common_history_start(staggered) == staggered.index[25]


def test_common_history_start_raises_on_empty_panel() -> None:
    empty = pd.DataFrame(
        {"AAA": [np.nan, np.nan]}, index=pd.bdate_range("2020-01-01", periods=2)
    )
    with pytest.raises(ValueError, match="any valid data"):
        common_history_start(empty)


def test_compare_vendors_reports_zero_disagreement_for_identical_panels(
    clean_panel: pd.DataFrame,
) -> None:
    result = compare_vendors(clean_panel, clean_panel.copy())
    assert (result["disagree_days"] == 0).all()
    assert result["return_corr"].round(6).eq(1.0).all()


def test_compare_vendors_detects_a_structural_break(
    clean_panel: pd.DataFrame,
) -> None:
    """A mis-applied split in one vendor shows up as disagreement."""
    other = clean_panel.copy()
    other.iloc[50:, 0] /= 2.0  # unadjusted 2:1 split in vendor B
    result = compare_vendors(clean_panel, other, tolerance=0.005)
    assert result.loc["AAA", "disagree_days"] >= 1
    assert result.loc["BBB", "disagree_days"] == 0
    assert result.loc["AAA", "max_abs_diff"] > 0.4
