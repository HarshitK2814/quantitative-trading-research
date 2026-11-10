"""Tests for session schedule (DST-safe)."""

from __future__ import annotations

from datetime import UTC, datetime

from src.intraday.schedule import current_session


def test_winter_open_session():  # EST = UTC-5, 09:45 ET = 14:45 UTC
    assert current_session(datetime(2026, 11, 10, 14, 50, tzinfo=UTC)) == "open"


def test_summer_open_session():  # EDT = UTC-4, 09:45 ET = 13:45 UTC
    assert current_session(datetime(2026, 7, 10, 13, 50, tzinfo=UTC)) == "open"


def test_all_five_sessions_winter():
    cases = {"open": (14, 45), "late_morning": (16, 30), "afternoon": (19, 0),
             "pre_close": (20, 45), "evening_crypto": (1, 0)}
    for name, (h, m) in cases.items():
        day = 11 if name == "evening_crypto" else 10
        assert current_session(datetime(2026, 11, day, h, m, tzinfo=UTC)) == name


def test_off_hours_returns_none():
    assert current_session(datetime(2026, 11, 10, 17, 30, tzinfo=UTC)) is None


def test_late_cron_within_tolerance():
    assert current_session(datetime(2026, 11, 10, 15, 8, tzinfo=UTC)) == "open"
