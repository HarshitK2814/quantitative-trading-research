"""Deflated Sharpe ratio, checked against closed-form values."""

from __future__ import annotations

import pytest

from src.overfitting import deflated_sharpe_ratio, expected_max_sharpe


def test_expected_max_sharpe_single_trial_is_zero() -> None:
    assert expected_max_sharpe(1, 0.04) == 0.0


def test_expected_max_sharpe_ten_trials_unit_variance() -> None:
    # g=0.5772: 0.4228*Phi^-1(0.9) + 0.5772*Phi^-1(1-1/(10e)) ~= 1.575
    assert expected_max_sharpe(10, 1.0) == pytest.approx(1.575, abs=0.02)


def test_expected_max_sharpe_scales_with_sqrt_variance() -> None:
    assert expected_max_sharpe(10, 4.0) == pytest.approx(
        2 * expected_max_sharpe(10, 1.0)
    )


def test_expected_max_sharpe_grows_with_trials() -> None:
    assert expected_max_sharpe(100, 1.0) > expected_max_sharpe(10, 1.0)


def test_dsr_one_trial_matches_probabilistic_sharpe() -> None:
    # Normal returns, SR=0.05/period, T=1001: z = 0.05*sqrt(1000)/1.00062
    value = deflated_sharpe_ratio(0.05, 1001, 1, 0.0)
    assert value == pytest.approx(0.943, abs=0.002)


def test_dsr_falls_as_trial_count_rises() -> None:
    few = deflated_sharpe_ratio(0.05, 1001, 5, 0.0004)
    many = deflated_sharpe_ratio(0.05, 1001, 500, 0.0004)
    assert many < few


def test_dsr_is_a_probability_and_high_for_huge_sharpe() -> None:
    assert 0.0 <= deflated_sharpe_ratio(0.01, 100, 50, 0.001) <= 1.0
    assert deflated_sharpe_ratio(0.5, 2000, 10, 0.001) > 0.999


def test_dsr_penalises_negative_skew_and_fat_tails() -> None:
    base = deflated_sharpe_ratio(0.05, 1001, 1, 0.0)
    worse = deflated_sharpe_ratio(0.05, 1001, 1, 0.0, skewness=-1.5, kurtosis=9.0)
    assert worse < base
