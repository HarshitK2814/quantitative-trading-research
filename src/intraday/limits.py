"""Hard risk limits and persistent state for the multi-session trader."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SessionLimits:
    """Risk limits. All are fractions of account equity unless noted."""

    max_position_pct: float = 0.05
    max_class_pct: float = 0.30
    daily_loss_halt_pct: float = 0.01
    kill_switch_drawdown_pct: float = 0.08
    min_order_usd: float = 50.0


def _default_state() -> dict:
    return {"peak_equity": 0.0, "day": "", "day_start_equity": 0.0,
            "killed": False, "ran": []}


def load_state(path: Path) -> dict:
    """Load state, or return a fresh default if the file does not exist."""
    path = Path(path)
    if path.exists():
        return {**_default_state(), **json.loads(path.read_text())}
    return _default_state()


def save_state(path: Path, state: dict) -> None:
    """Write state as JSON, creating parent folders."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


def update_state(state: dict, equity: float, today: str, limits: SessionLimits) -> dict:
    """Return new state with day roll-over, peak and kill-switch applied."""
    s = dict(state)
    s["ran"] = list(s["ran"])
    if s["day"] != today:
        s["day"] = today
        s["day_start_equity"] = equity
        s["ran"] = []
    s["peak_equity"] = max(s["peak_equity"], equity)
    floor = s["peak_equity"] * (1 - limits.kill_switch_drawdown_pct)
    if s["peak_equity"] > 0 and equity <= floor:
        s["killed"] = True  # latched: only a manual edit clears it
    return s


def buys_allowed(state: dict, equity: float, limits: SessionLimits) -> tuple[bool, str]:
    """Return (allowed, reason). Sells are never blocked by this check."""
    if state["killed"]:
        return False, "kill switch active"
    start = state["day_start_equity"]
    if start > 0 and equity <= start * (1 - limits.daily_loss_halt_pct):
        return False, "daily loss limit hit"
    return True, "ok"


def cap_weights(
    weights: dict[str, float], groups: dict[str, str], limits: SessionLimits
) -> dict[str, float]:
    """Cap each weight, then scale each asset class down to its class cap."""
    capped = {s: min(w, limits.max_position_pct) for s, w in weights.items()}
    for g in set(groups[s] for s in capped):
        syms = [s for s in capped if groups[s] == g]
        total = sum(capped[s] for s in syms)
        if total > limits.max_class_pct:
            k = limits.max_class_pct / total
            for s in syms:
                capped[s] *= k
    return capped
