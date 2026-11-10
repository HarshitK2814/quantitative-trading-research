"""Tests for session risk limits and state."""

from __future__ import annotations

import pytest

from src.intraday.limits import (
    SessionLimits,
    buys_allowed,
    cap_weights,
    load_state,
    save_state,
    update_state,
)

L = SessionLimits()


def test_new_day_resets_day_start_and_ran(tmp_path):
    s = load_state(tmp_path / "s.json")
    s = update_state(s, 100_000, "2026-11-10", L)
    s["ran"].append("2026-11-10:open")
    s = update_state(s, 100_500, "2026-11-11", L)
    assert s["day_start_equity"] == 100_500
    assert s["ran"] == []
    assert s["peak_equity"] == 100_500


def test_daily_loss_blocks_buys():
    s = update_state(load_state_default(), 100_000, "d", L)
    ok, _ = buys_allowed(s, 98_900, L)  # -1.1%
    assert not ok
    ok, _ = buys_allowed(s, 99_500, L)  # -0.5%
    assert ok


def test_kill_switch_latches():
    s = update_state(load_state_default(), 100_000, "d", L)
    s = update_state(s, 91_000, "d", L)  # -9% from peak
    assert s["killed"] is True
    s = update_state(s, 100_000, "d", L)  # recovery does not clear it
    assert s["killed"] is True
    ok, why = buys_allowed(s, 100_000, L)
    assert not ok and "kill" in why


def test_cap_weights_position_and_class():
    groups = {f"E{i}": "etf" for i in range(6)} | {"A": "stock"}
    w = {f"E{i}": 0.07 for i in range(6)} | {"A": 0.20}
    out = cap_weights(w, groups, L)
    assert out["A"] == pytest.approx(0.05)
    assert sum(out[f"E{i}"] for i in range(6)) == pytest.approx(0.30)


def test_state_roundtrip(tmp_path):
    p = tmp_path / "x" / "s.json"
    save_state(p, {"peak_equity": 1.0})
    assert load_state(p)["peak_equity"] == 1.0


def load_state_default():
    return {"peak_equity": 0.0, "day": "", "day_start_equity": 0.0,
            "killed": False, "ran": []}
