"""Four daily trading sessions before 12:00 ET (user asleep 23:00-08:00 IST); US Eastern, DST-safe."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

#: name -> (hour, minute) Eastern.
SESSIONS: dict[str, tuple[int, int]] = {
    "open": (9, 45),
    "mid_morning": (10, 30),
    "late_morning": (11, 15),
    "noon": (11, 45),
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
