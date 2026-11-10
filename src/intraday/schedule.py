"""Five daily trading sessions, defined in US Eastern time (DST-safe)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

#: name -> (hour, minute) Eastern.
SESSIONS: dict[str, tuple[int, int]] = {
    "open": (9, 45),
    "late_morning": (11, 30),
    "afternoon": (14, 0),
    "pre_close": (15, 45),
    "evening_crypto": (20, 0),
}


def current_session(now_utc: datetime, tolerance_min: int = 25) -> str | None:
    """Return the session whose time is within tolerance of now, else None.

    Cron fires at both the EDT and EST UTC hours; only the one that lands near
    a session time in real Eastern time is accepted. Tolerance absorbs GitHub's
    cron delay.
    """
    now = now_utc.astimezone(ET)
    for name, (h, m) in SESSIONS.items():
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if 0 <= (now - target).total_seconds() / 60 <= tolerance_min:
            return name
    return None
