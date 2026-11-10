# Multi-Session Autonomous Paper Trader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A bot that trades 5 times per US trading day on a dedicated Alpaca **paper** account, using pre-registered strategies, a Groq news veto, hard loss limits, and a verifiable log.

**Architecture:** New package `src/intraday/` (pure, testable modules) plus `scripts/run_session.py` (CLI) and a GitHub Actions cron workflow. Existing H1 daily run and its account are untouched: the session trader uses its **own** Alpaca paper account, so its record is clean. State and logs are committed back to the repo after each run (Actions is stateless).

**Tech Stack:** Python 3.12, pandas, numpy, requests, yfinance (daily bars), Alpaca paper REST (`src/broker.py`), Groq OpenAI-compatible API (free tier), pytest, GitHub Actions.

## Global Constraints

Copied from `.plans/multi-session-autonomous-trader-spec.md`:
- Paper only. Reuse `src.config.load_broker_config` (it blocks non-paper endpoints). Never add a live path.
- Groq LLM may only **veto or halve** a buy. It never adds risk and never gates sells.
- If Groq fails or `GROQ_API_KEY` is missing, buys are skipped (fail safe). Sells still run.
- Limits (configurable in `SessionLimits`): 5% max per position, 30% max per asset class, 1% daily loss halt (no new buys), 8% drawdown kill-switch (needs manual reset), 8% per-position stop (`src.config.RISK.stop_loss_pct`), no leverage, no shorting.
- Each strategy is pre-registered in `research/hypotheses_sessions.md` and committed **before** the gate is run. A strategy is switched on only if it passes. Failures are recorded.
- Resume: no profit claim. Short record is noise; reports say so.
- Universe: liquid US ETFs, large-cap US stocks, crypto (Alpaca paper).

Deviation to note: the spec said "20% per sector". We have no sector data, so the plan uses a 30% **asset-class** cap. The ETF sleeve is 6 funds at 5% each = 30%.

## File Structure

| File | Responsibility |
|---|---|
| `src/intraday/__init__.py` | Package marker |
| `src/intraday/limits.py` | `SessionLimits`, state load/save/update, `buys_allowed`, `cap_weights` |
| `src/intraday/strategies.py` | Signals (trend, RSI2), `StrategySpec`, `REGISTRY`, `target_weights`, `completed_bars` |
| `src/intraday/validate.py` | `backtest_returns`, `gate` (pre-registered pass/fail) |
| `src/intraday/schedule.py` | `current_session(now_utc)` for 5 daily sessions (DST-safe) |
| `src/intraday/news.py` | `fetch_headlines` (Alpaca news API) |
| `src/intraday/groq_gate.py` | `Verdict`, `review_trade` (Groq veto/reduce) |
| `src/intraday/prices.py` | `to_yf`, `load_daily_closes`, `crypto_last_prices` |
| `src/intraday/session.py` | `run_session` orchestrator + CSV log |
| `src/intraday/report.py` | `summarize` equity stats vs benchmark |
| `scripts/run_session.py` | CLI entry (dry run by default) |
| `scripts/run_session_gate.py` | Runs the pre-registered gate, prints pass/fail |
| `scripts/weekly_report.py` | Writes `reports/weekly/YYYY-MM-DD.md` |
| `research/hypotheses_sessions.md` | Pre-registration of S1-S3 |
| `.github/workflows/sessions.yml` | Cron runner |
| `tests/intraday/test_*.py` | Tests for each module |

---

### Task 1: Risk limits and persistent state

**Files:**
- Create: `src/intraday/__init__.py`, `src/intraday/limits.py`, `tests/intraday/__init__.py`, `tests/intraday/test_limits.py`

**Interfaces:**
- Produces: `SessionLimits` (frozen dataclass), `load_state(path) -> dict`, `save_state(path, state)`, `update_state(state, equity, today, limits) -> dict`, `buys_allowed(state, equity, limits) -> tuple[bool, str]`, `cap_weights(weights, groups, limits) -> dict[str, float]`.

- [ ] **Step 1: Write the failing test** in `tests/intraday/test_limits.py`

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. python -m pytest tests/intraday/test_limits.py -v`
Expected: FAIL `ModuleNotFoundError: src.intraday`

- [ ] **Step 3: Implement.** `src/intraday/__init__.py` and `tests/intraday/__init__.py` are empty files. `src/intraday/limits.py`:

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=. python -m pytest tests/intraday/test_limits.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/intraday tests/intraday
git commit -m "feat(intraday): risk limits and persistent state"
```

---

### Task 2: Pre-registered strategies and validation gate

**Files:**
- Create: `research/hypotheses_sessions.md`, `src/intraday/strategies.py`, `src/intraday/validate.py`, `scripts/run_session_gate.py`, `tests/intraday/test_strategies.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `trend_signal(close, fast, slow) -> pd.Series`, `meanrev_signal(close) -> pd.Series`, `StrategySpec`, `REGISTRY: dict[str, StrategySpec]`, `target_weights(registry, closes) -> dict[str, float]`, `completed_bars(close, today: date) -> pd.Series`, `backtest_returns(closes, signal_fn, cost_bps=5.0) -> pd.Series`, `gate(returns, start="2021-01-01") -> dict`.

- [ ] **Step 1: Pre-register first.** Write `research/hypotheses_sessions.md` and commit it BEFORE any code or backtest:

```markdown
# Session-trader hypotheses (pre-registered 2026-11-10)

Parameters are the textbook values, fixed now, never tuned. Committed before any backtest.

| ID | Rule | Universe | Capital |
|---|---|---|---|
| S1 | Long when close > SMA200 and SMA50 > SMA200, else flat | SPY, QQQ, XLK, XLF, XLE, XLV | 40% |
| S2 | Long when RSI(2) < 10 and close > SMA200; exit when RSI(2) > 70 | AAPL, MSFT, NVDA, AMZN, GOOGL | 30% |
| S3 | Long when close > SMA100 and SMA20 > SMA100, else flat | BTC/USD, ETH/USD | 30% |

Signals use completed daily bars only (one-bar lag). Cost: 5 bps per unit turnover.

## Pass/fail gate (held-out window 2021-01-01 to latest)
A strategy is switched on only if, equal-weighted across its universe:
- annualised Sharpe >= 0.5, AND
- max drawdown no worse than -25%.

Fail = stays off. Result is recorded in `research/daily_log.md` either way.
No re-tuning after seeing results.
```

```bash
git add research/hypotheses_sessions.md
git commit -m "research: pre-register session strategies S1-S3 before testing"
```

- [ ] **Step 2: Write the failing test** `tests/intraday/test_strategies.py`

```python
"""Tests for session strategies and the validation gate."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from src.intraday.strategies import (
    REGISTRY,
    StrategySpec,
    completed_bars,
    meanrev_signal,
    target_weights,
    trend_signal,
)
from src.intraday.validate import backtest_returns, gate


def _series(values, start="2020-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values)))


def test_trend_long_in_uptrend_flat_in_downtrend():
    up = _series(np.linspace(100, 300, 300))
    down = _series(np.linspace(300, 100, 300))
    assert trend_signal(up, 50, 200).iloc[-1] == 1.0
    assert trend_signal(down, 50, 200).iloc[-1] == 0.0


def test_trend_flat_during_warmup():
    assert trend_signal(_series(np.linspace(1, 2, 100)), 50, 200).sum() == 0.0


def test_meanrev_enters_on_dip_in_uptrend_and_exits_on_bounce():
    base = list(np.linspace(100, 200, 250))
    dip = base + [190.0, 180.0]          # sharp drop, still above SMA200
    assert meanrev_signal(_series(dip)).iloc[-1] == 1.0
    bounce = dip + [195.0, 205.0, 215.0]
    assert meanrev_signal(_series(bounce)).iloc[-1] == 0.0


def test_completed_bars_drops_todays_bar():
    s = _series([1.0, 2.0, 3.0], start="2026-11-08")  # 8,9,10 Nov
    assert len(completed_bars(s, date(2026, 11, 10))) == 2
    assert len(completed_bars(s, date(2026, 11, 11))) == 3


def test_target_weights_only_active_and_split_equally():
    up = _series(np.linspace(100, 300, 300))
    spec_on = StrategySpec("T1", ("A", "B"), "etf", 0.4,
                           lambda c: trend_signal(c, 50, 200), True)
    spec_off = StrategySpec("T2", ("C",), "stock", 0.3,
                            lambda c: trend_signal(c, 50, 200), False)
    w = target_weights({"T1": spec_on, "T2": spec_off},
                       {"A": up, "B": up, "C": up})
    assert w == {"A": 0.2, "B": 0.2}


def test_target_weights_missing_data_is_zero():
    spec = StrategySpec("T1", ("A",), "etf", 0.4,
                        lambda c: trend_signal(c, 50, 200), True)
    assert target_weights({"T1": spec}, {})["A"] == 0.0


def test_registry_symbols_are_disjoint_and_fractions_fit():
    syms = [s for spec in REGISTRY.values() for s in spec.symbols]
    assert len(syms) == len(set(syms))
    assert sum(s.capital_fraction for s in REGISTRY.values()) <= 1.0


def test_backtest_uses_one_bar_lag_and_gate_thresholds():
    closes = pd.DataFrame({"A": np.linspace(100, 400, 1500)},
                          index=pd.date_range("2019-01-01", periods=1500))
    rets = backtest_returns(closes, lambda c: trend_signal(c, 50, 200))
    assert rets.iloc[:200].abs().sum() == 0.0   # flat during warmup
    g = gate(rets, start="2021-01-01")
    assert g["passed"] is True and g["sharpe"] > 0.5
    losing = pd.Series(-0.01, index=closes.index)
    assert gate(losing, start="2021-01-01")["passed"] is False
```

- [ ] **Step 3: Run to verify it fails**

Run: `PYTHONPATH=. python -m pytest tests/intraday/test_strategies.py -v`
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 4: Implement** `src/intraday/strategies.py`:

```python
"""Pre-registered signals. Parameters are fixed in research/hypotheses_sessions.md."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pandas as pd


def trend_signal(close: pd.Series, fast: int, slow: int) -> pd.Series:
    """1.0 when close > slow SMA and fast SMA > slow SMA, else 0.0."""
    f = close.rolling(fast).mean()
    s = close.rolling(slow).mean()
    return ((close > s) & (f > s)).astype(float)


def _rsi(close: pd.Series, n: int = 2) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn)).fillna(50.0)


def meanrev_signal(close: pd.Series) -> pd.Series:
    """Long when RSI(2)<10 and close>SMA200; exit when RSI(2)>70."""
    rsi = _rsi(close, 2).values
    sma = close.rolling(200).mean().values
    held, out = 0.0, []
    for c, r, s in zip(close.values, rsi, sma, strict=True):
        if held == 0.0 and r < 10.0 and c > s:   # NaN sma -> False
            held = 1.0
        elif held == 1.0 and r > 70.0:
            held = 0.0
        out.append(held)
    return pd.Series(out, index=close.index)


@dataclass(frozen=True)
class StrategySpec:
    """One pre-registered strategy."""

    id: str
    symbols: tuple[str, ...]
    asset_class: str  # "etf" | "stock" | "crypto"
    capital_fraction: float
    signal_fn: Callable[[pd.Series], pd.Series]
    active: bool = False  # flipped only after the gate passes (Task 7)


REGISTRY: dict[str, StrategySpec] = {
    "S1": StrategySpec(
        "S1", ("SPY", "QQQ", "XLK", "XLF", "XLE", "XLV"), "etf", 0.40,
        lambda c: trend_signal(c, 50, 200),
    ),
    "S2": StrategySpec(
        "S2", ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"), "stock", 0.30,
        meanrev_signal,
    ),
    "S3": StrategySpec(
        "S3", ("BTC/USD", "ETH/USD"), "crypto", 0.30,
        lambda c: trend_signal(c, 20, 100),
    ),
}


def completed_bars(close: pd.Series, today: date) -> pd.Series:
    """Drop any bar dated today (it is still forming), keeping the one-bar lag."""
    if len(close) and close.index[-1].date() >= today:
        return close[close.index.date < today]
    return close


def target_weights(
    registry: dict[str, StrategySpec], closes: dict[str, pd.Series]
) -> dict[str, float]:
    """Weight per symbol for active strategies; missing data means 0."""
    out: dict[str, float] = {}
    for spec in registry.values():
        if not spec.active:
            continue
        for sym in spec.symbols:
            c = closes.get(sym)
            if c is None or len(c) == 0:
                out[sym] = 0.0
                continue
            sig = float(spec.signal_fn(c).iloc[-1])
            out[sym] = sig * spec.capital_fraction / len(spec.symbols)
    return out
```

`src/intraday/validate.py`:

```python
"""Backtest and the pre-registered pass/fail gate."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

SHARPE_MIN = 0.5
MAX_DD_FLOOR = -0.25


def backtest_returns(
    closes: pd.DataFrame,
    signal_fn: Callable[[pd.Series], pd.Series],
    cost_bps: float = 5.0,
) -> pd.Series:
    """Equal-weight daily returns across columns, signal lagged one bar."""
    per_asset = []
    for col in closes.columns:
        c = closes[col].dropna()
        pos = signal_fn(c).shift(1).fillna(0.0)
        gross = pos * c.pct_change().fillna(0.0)
        cost = pos.diff().abs().fillna(0.0) * cost_bps / 1e4
        per_asset.append(gross - cost)
    return pd.concat(per_asset, axis=1).mean(axis=1)


def gate(returns: pd.Series, start: str = "2021-01-01") -> dict:
    """Apply the pre-registered thresholds on the held-out window."""
    r = returns[returns.index >= pd.Timestamp(start)]
    std = r.std()
    sharpe = float(r.mean() / std * np.sqrt(252)) if std > 0 else 0.0
    equity = (1 + r).cumprod()
    max_dd = float((equity / equity.cummax() - 1).min()) if len(r) else 0.0
    passed = sharpe >= SHARPE_MIN and max_dd >= MAX_DD_FLOOR
    return {"sharpe": sharpe, "max_drawdown": max_dd, "passed": bool(passed),
            "days": int(len(r))}
```

`scripts/run_session_gate.py`:

```python
"""Run the pre-registered gate for S1-S3 and print pass/fail.

    PYTHONPATH=. python scripts/run_session_gate.py
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf

from src.intraday.prices import to_yf
from src.intraday.strategies import REGISTRY
from src.intraday.validate import backtest_returns, gate


def main() -> None:
    for spec in REGISTRY.values():
        yf_syms = [to_yf(s) for s in spec.symbols]
        raw = yf.download(yf_syms, start="2015-01-01", auto_adjust=True,
                          progress=False)["Close"]
        if isinstance(raw, pd.Series):
            raw = raw.to_frame(yf_syms[0])
        result = gate(backtest_returns(raw.dropna(how="all"), spec.signal_fn))
        print(spec.id, result)


if __name__ == "__main__":
    main()
```

(`to_yf` is created in Task 5; this script is run in Task 7. Until then it is not executed.)

- [ ] **Step 5: Run to verify it passes**

Run: `PYTHONPATH=. python -m pytest tests/intraday/test_strategies.py -v`
Expected: 8 passed. If `test_meanrev_*` fails, print `_rsi` on the tail of the fixture and adjust the fixture (not the thresholds, which are pre-registered).

- [ ] **Step 6: Commit**

```bash
git add src/intraday scripts/run_session_gate.py tests/intraday
git commit -m "feat(intraday): pre-registered strategies S1-S3 and validation gate"
```

---

### Task 3: Session schedule

**Files:**
- Create: `src/intraday/schedule.py`, `tests/intraday/test_schedule.py`

**Interfaces:**
- Produces: `SESSIONS: dict[str, tuple[int, int]]` (ET hour, minute), `current_session(now_utc: datetime, tolerance_min: int = 25) -> str | None`.

- [ ] **Step 1: Failing test**

```python
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
```

- [ ] **Step 2: Run, expect FAIL** (`ModuleNotFoundError`).
Run: `PYTHONPATH=. python -m pytest tests/intraday/test_schedule.py -v`

- [ ] **Step 3: Implement**

```python
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
```

- [ ] **Step 4: Run, expect 5 passed.**
- [ ] **Step 5: Commit**

```bash
git add src/intraday/schedule.py tests/intraday/test_schedule.py
git commit -m "feat(intraday): DST-safe five-session schedule"
```

---

### Task 4: News fetch and Groq veto gate

**Files:**
- Create: `src/intraday/news.py`, `src/intraday/groq_gate.py`, `tests/intraday/test_news_gate.py`

**Interfaces:**
- Produces: `fetch_headlines(symbols, key_id, secret, limit=5, get=requests.get) -> dict[str, list[str]]`; `Verdict(action, reason)` frozen dataclass; `review_trade(symbol, headlines, api_key, post=requests.post) -> Verdict` where action is `"ok" | "reduce" | "veto"`.

- [ ] **Step 1: Failing test**

```python
"""Tests for news fetch and Groq gate (no network)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from src.intraday.groq_gate import review_trade
from src.intraday.news import fetch_headlines


def _resp(payload, status=200):
    return SimpleNamespace(status_code=status, json=lambda: payload,
                           raise_for_status=lambda: None)


def _groq(content):
    return lambda *a, **k: _resp({"choices": [{"message": {"content": content}}]})


def test_headlines_grouped_by_symbol_and_crypto_slash_removed():
    seen = {}

    def fake_get(url, params, headers, timeout):
        seen["symbols"] = params["symbols"]
        return _resp({"news": [{"headline": "Up", "symbols": ["AAPL"]},
                               {"headline": "BTC jumps", "symbols": ["BTCUSD"]}]})

    out = fetch_headlines(["AAPL", "BTC/USD"], "k", "s", get=fake_get)
    assert seen["symbols"] == "AAPL,BTCUSD"
    assert out["AAPL"] == ["Up"] and out["BTC/USD"] == ["BTC jumps"]


def test_headlines_error_returns_empty():
    def boom(*a, **k):
        raise RuntimeError("down")

    assert fetch_headlines(["AAPL"], "k", "s", get=boom) == {"AAPL": []}


def test_no_headlines_means_ok_without_calling_groq():
    def must_not_call(*a, **k):
        raise AssertionError("called")

    assert review_trade("AAPL", [], "key", post=must_not_call).action == "ok"


def test_veto_and_reduce_parsed():
    v = review_trade("AAPL", ["Fraud probe"], "key",
                     post=_groq(json.dumps({"action": "veto", "reason": "fraud"})))
    assert v.action == "veto" and v.reason == "fraud"
    v = review_trade("AAPL", ["Mixed"], "key",
                     post=_groq(json.dumps({"action": "reduce", "reason": "mixed"})))
    assert v.action == "reduce"


def test_failures_fail_safe_to_veto():
    assert review_trade("AAPL", ["x"], "", post=_groq("{}")).action == "veto"   # no key
    assert review_trade("AAPL", ["x"], "key", post=_groq("not json")).action == "veto"
    assert review_trade("AAPL", ["x"], "key",
                        post=_groq(json.dumps({"action": "buy_more"}))).action == "veto"

    def boom(*a, **k):
        raise RuntimeError("429")

    assert review_trade("AAPL", ["x"], "key", post=boom).action == "veto"
```

- [ ] **Step 2: Run, expect FAIL.** `PYTHONPATH=. python -m pytest tests/intraday/test_news_gate.py -v`

- [ ] **Step 3: Implement.** `src/intraday/news.py`:

```python
"""Headlines from the Alpaca news API (free with paper keys)."""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)
NEWS_URL = "https://data.alpaca.markets/v1beta1/news"


def _api_symbol(sym: str) -> str:
    return sym.replace("/", "")


def fetch_headlines(
    symbols: list[str], key_id: str, secret: str, limit: int = 5, get=requests.get
) -> dict[str, list[str]]:
    """Return up to ``limit`` recent headlines per symbol. Errors give empty lists."""
    out: dict[str, list[str]] = {s: [] for s in symbols}
    try:
        resp = get(
            NEWS_URL,
            params={"symbols": ",".join(_api_symbol(s) for s in symbols),
                    "limit": 50, "sort": "desc"},
            headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret},
            timeout=20,
        )
        resp.raise_for_status()
        by_api = {_api_symbol(s): s for s in symbols}
        for item in resp.json().get("news", []):
            for api_sym in item.get("symbols", []):
                sym = by_api.get(api_sym)
                if sym and len(out[sym]) < limit:
                    out[sym].append(item["headline"])
    except Exception as exc:  # news is advisory; never crash a session
        logger.warning("news fetch failed: %s", exc)
    return out
```

`src/intraday/groq_gate.py`:

```python
"""Groq LLM news check. It can only veto or halve a BUY, never add risk."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"
_VALID = {"ok", "reduce", "veto"}

PROMPT = (
    "You are a risk reviewer for a paper-trading bot that wants to BUY {symbol}. "
    "Headlines:\n{headlines}\n\n"
    'Reply with JSON only: {{"action": "ok"|"reduce"|"veto", "reason": "<12 words"}}. '
    "veto = serious negative news (fraud, bankruptcy, guidance cut, hack, "
    "regulatory action). reduce = mixed or uncertain. ok = nothing alarming. "
    "You may not recommend buying more."
)


@dataclass(frozen=True)
class Verdict:
    """Gate decision."""

    action: str  # "ok" | "reduce" | "veto"
    reason: str


def review_trade(
    symbol: str, headlines: list[str], api_key: str, post=requests.post
) -> Verdict:
    """Ask Groq to review a buy. Any failure returns a veto (fail safe)."""
    if not headlines:
        return Verdict("ok", "no news")
    if not api_key:
        return Verdict("veto", "GROQ_API_KEY missing")
    try:
        resp = post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": MODEL,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": PROMPT.format(
                    symbol=symbol,
                    headlines="\n".join(f"- {h}" for h in headlines))}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = json.loads(resp.json()["choices"][0]["message"]["content"])
        action = data.get("action")
        if action not in _VALID:
            return Verdict("veto", f"invalid action {action!r}")
        return Verdict(action, str(data.get("reason", ""))[:200])
    except Exception as exc:
        logger.warning("groq gate failed: %s", exc)
        return Verdict("veto", "gate unavailable")
```

- [ ] **Step 4: Run, expect 5 passed.**
- [ ] **Step 5: Commit**

```bash
git add src/intraday/news.py src/intraday/groq_gate.py tests/intraday/test_news_gate.py
git commit -m "feat(intraday): Alpaca news fetch and Groq veto gate"
```

---

### Task 5: Prices and the session orchestrator

**Files:**
- Create: `src/intraday/prices.py`, `src/intraday/session.py`, `scripts/run_session.py`, `tests/intraday/test_session.py`

**Interfaces:**
- Consumes: `SessionLimits`, `load_state`, `save_state`, `update_state`, `buys_allowed`, `cap_weights` (Task 1); `StrategySpec`, `target_weights` (Task 2); `Verdict` (Task 4); `src.broker.Position`, `AccountSnapshot`; `src.config.RISK`.
- Produces: `to_yf(sym) -> str`, `load_daily_closes(symbols) -> dict[str, pd.Series]`, `crypto_last_prices(symbols, key_id, secret, get=requests.get) -> dict[str, float]`, `run_session(...) -> list[dict]`.

- [ ] **Step 1: Failing test** `tests/intraday/test_session.py`

```python
"""Tests for the session orchestrator using a fake broker."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd

from src.broker import AccountSnapshot, Position
from src.intraday.groq_gate import Verdict
from src.intraday.limits import SessionLimits
from src.intraday.prices import to_yf
from src.intraday.session import run_session
from src.intraday.strategies import StrategySpec, trend_signal

NOW = datetime(2026, 11, 10, 14, 50, tzinfo=UTC)
UP = pd.Series(np.linspace(100, 300, 300), index=pd.date_range("2025-01-01", periods=300))
DOWN = UP[::-1].set_axis(UP.index)


class FakeBroker:
    def __init__(self, equity=100_000.0, positions=None, market_open=True):
        self.equity, self.positions, self.market_open = equity, positions or {}, market_open
        self.orders = []

    def get_account(self):
        return AccountSnapshot("a", self.equity, self.equity, self.equity, self.equity,
                               "ACTIVE", False, NOW)

    def get_positions(self):
        return self.positions

    def is_market_open(self):
        return self.market_open

    def submit_order(self, symbol, qty, side, time_in_force="day", **kw):
        self.orders.append((symbol, qty, side, time_in_force))
        return SimpleNamespace(order_id=f"id{len(self.orders)}")


def _spec(symbols=("A",), cls="etf", active=True):
    return {"T": StrategySpec("T", symbols, cls, 0.4,
                              lambda c: trend_signal(c, 50, 200), active)}


def _run(tmp_path, broker, closes, registry, gate=None, dry_run=False, prices=None):
    return run_session(
        name="open", broker=broker, closes=closes, now_utc=NOW,
        limits=SessionLimits(), state_path=tmp_path / "s.json",
        log_path=tmp_path / "log.csv", registry=registry,
        gate=gate or (lambda s: Verdict("ok", "")),
        prices=prices or {"A": 100.0}, dry_run=dry_run,
    )


def test_buy_sized_to_cap_and_logged(tmp_path):
    b = FakeBroker()
    rows = _run(tmp_path, b, {"A": UP}, _spec())
    assert b.orders == [("A", 50, "buy", "day")]      # 5% of 100k / $100
    assert rows[0]["side"] == "buy" and (tmp_path / "log.csv").exists()


def test_dry_run_places_no_orders(tmp_path):
    b = FakeBroker()
    rows = _run(tmp_path, b, {"A": UP}, _spec(), dry_run=True)
    assert b.orders == [] and rows[0]["dry_run"] is True


def test_veto_blocks_buy_but_not_sell(tmp_path):
    b = FakeBroker()
    _run(tmp_path, b, {"A": UP}, _spec(), gate=lambda s: Verdict("veto", "bad"))
    assert b.orders == []
    held = {"A": Position("A", 50, 5000, 100, 100, 0)}
    b2 = FakeBroker(positions=held)
    _run(tmp_path / "2", b2, {"A": DOWN}, _spec(), gate=lambda s: Verdict("veto", "bad"))
    assert b2.orders == [("A", 50, "sell", "day")]


def test_reduce_halves_buy(tmp_path):
    b = FakeBroker()
    _run(tmp_path, b, {"A": UP}, _spec(), gate=lambda s: Verdict("reduce", "mixed"))
    assert b.orders[0][1] == 25


def test_stop_loss_forces_exit_even_if_signal_long(tmp_path):
    held = {"A": Position("A", 50, 4500, 100, 90, -500)}   # -10% > 8% stop
    b = FakeBroker(positions=held)
    _run(tmp_path, b, {"A": UP}, _spec(), prices={"A": 90.0})
    assert b.orders == [("A", 50, "sell", "day")]


def test_kill_switch_blocks_buys_allows_sells(tmp_path):
    (tmp_path / "s.json").write_text('{"peak_equity": 200000, "killed": true}')
    b = FakeBroker()
    _run(tmp_path, b, {"A": UP}, _spec())
    assert b.orders == []


def test_stocks_skipped_when_market_closed_crypto_trades(tmp_path):
    b = FakeBroker(market_open=False)
    reg = {**_spec(("A",), "etf"), "C": StrategySpec(
        "C", ("BTC/USD",), "crypto", 0.3, lambda c: trend_signal(c, 50, 200), True)}
    _run(tmp_path, b, {"A": UP, "BTC/USD": UP}, reg, prices={"A": 100.0, "BTC/USD": 50_000.0})
    assert [o[0] for o in b.orders] == ["BTC/USD"]
    assert b.orders[0][3] == "gtc" and b.orders[0][1] == 0.1   # 5% of 100k / 50k


def test_session_runs_once_per_day(tmp_path):
    b = FakeBroker()
    _run(tmp_path, b, {"A": UP}, _spec())
    _run(tmp_path, b, {"A": UP}, _spec())
    assert len(b.orders) == 1


def test_untracked_positions_are_never_touched(tmp_path):
    held = {"ZZZ": Position("ZZZ", 10, 1000, 100, 100, 0)}
    b = FakeBroker(positions=held)
    _run(tmp_path, b, {"A": UP}, _spec())
    assert all(o[0] != "ZZZ" for o in b.orders)


def test_to_yf_maps_crypto():
    assert to_yf("BTC/USD") == "BTC-USD" and to_yf("SPY") == "SPY"
```

- [ ] **Step 2: Run, expect FAIL.** `PYTHONPATH=. python -m pytest tests/intraday/test_session.py -v`

- [ ] **Step 3: Implement** `src/intraday/prices.py`:

```python
"""Price helpers: daily bars from Yahoo, crypto last trade from Alpaca."""

from __future__ import annotations

import pandas as pd
import requests
import yfinance as yf

CRYPTO_LATEST = "https://data.alpaca.markets/v1beta3/crypto/us/latest/trades"


def to_yf(sym: str) -> str:
    """Alpaca symbol -> Yahoo symbol (BTC/USD -> BTC-USD)."""
    return sym.replace("/", "-")


def load_daily_closes(symbols: list[str], start: str = "2023-01-01") -> dict[str, pd.Series]:
    """Daily adjusted closes keyed by Alpaca symbol."""
    out: dict[str, pd.Series] = {}
    raw = yf.download([to_yf(s) for s in symbols], start=start, auto_adjust=True,
                      progress=False)["Close"]
    if isinstance(raw, pd.Series):
        raw = raw.to_frame(to_yf(symbols[0]))
    for s in symbols:
        col = to_yf(s)
        if col in raw.columns:
            out[s] = raw[col].dropna()
    return out


def crypto_last_prices(symbols, key_id, secret, get=requests.get) -> dict[str, float]:
    """Latest crypto trade price per Alpaca symbol. Errors give an empty dict."""
    if not symbols:
        return {}
    try:
        r = get(CRYPTO_LATEST, params={"symbols": ",".join(symbols)},
                headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret},
                timeout=20)
        r.raise_for_status()
        return {s: float(t["p"]) for s, t in r.json().get("trades", {}).items()}
    except Exception:
        return {}
```

`src/intraday/session.py`:

```python
"""Run one trading session: signals -> caps -> news gate -> orders -> log."""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from src.config import RISK
from src.intraday.limits import (
    SessionLimits,
    buys_allowed,
    cap_weights,
    load_state,
    save_state,
    update_state,
)
from src.intraday.schedule import ET
from src.intraday.strategies import completed_bars, target_weights

logger = logging.getLogger(__name__)

LOG_FIELDS = ["ts", "session", "symbol", "strategy", "side", "qty", "price",
              "news_action", "news_reason", "note", "dry_run", "order_id"]


def _norm(sym: str) -> str:
    return sym.replace("/", "")


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def run_session(
    *, name, broker, closes, now_utc: datetime, limits: SessionLimits,
    state_path: Path, log_path: Path, registry, gate, prices: dict[str, float],
    dry_run: bool,
) -> list[dict]:
    """Run one session and return the log rows. Only registry symbols are touched."""
    today_et = now_utc.astimezone(ET).date()
    acct = broker.get_account()
    state = update_state(load_state(state_path), acct.equity, today_et.isoformat(), limits)
    key = f"{today_et.isoformat()}:{name}"
    if key in state["ran"]:
        save_state(state_path, state)
        return []
    state["ran"].append(key)

    closes = {s: completed_bars(c, today_et) for s, c in closes.items()}
    owner = {s: spec.id for spec in registry.values() if spec.active for s in spec.symbols}
    classes = {s: spec.asset_class for spec in registry.values() if spec.active
               for s in spec.symbols}
    weights = cap_weights(target_weights(registry, closes), classes, limits)

    positions = {_norm(s): p for s, p in broker.get_positions().items()}
    notes: dict[str, str] = {}
    for sym in weights:
        pos = positions.get(_norm(sym))
        if pos and pos.avg_entry_price > 0 and \
                pos.current_price <= pos.avg_entry_price * (1 - RISK.stop_loss_pct):
            weights[sym] = 0.0
            notes[sym] = "stop-loss"

    allowed, why = buys_allowed(state, acct.equity, limits)
    market_open = broker.is_market_open()
    rows: list[dict] = []

    def log(sym, side, qty, price, verdict=None, note="", order_id=""):
        row = {"ts": now_utc.isoformat(), "session": name, "symbol": sym,
               "strategy": owner[sym], "side": side, "qty": qty, "price": price,
               "news_action": getattr(verdict, "action", ""),
               "news_reason": getattr(verdict, "reason", ""),
               "note": note, "dry_run": dry_run, "order_id": order_id}
        _append(log_path, row)
        rows.append(row)

    for sym, w in weights.items():
        is_crypto = classes[sym] == "crypto"
        if not is_crypto and not market_open:
            continue
        price = prices.get(sym)
        if not price:
            continue
        pos = positions.get(_norm(sym))
        held_val = pos.market_value if pos else 0.0
        delta = w * acct.equity - held_val
        if abs(delta) < limits.min_order_usd:
            continue
        side = "buy" if delta > 0 else "sell"
        verdict = None
        if side == "buy":
            if not allowed:
                log(sym, "skip", 0, price, note=why)
                continue
            verdict = gate(sym)
            if verdict.action == "veto":
                log(sym, "skip", 0, price, verdict, "news veto")
                continue
            if verdict.action == "reduce":
                delta *= 0.5
        if side == "sell" and w == 0.0 and pos:
            qty = pos.qty
        else:
            qty = abs(delta) / price
            qty = round(qty, 6) if is_crypto else int(qty)
            if side == "sell" and pos:
                qty = min(qty, pos.qty)
        if qty <= 0:
            continue
        order_id = ""
        if not dry_run:
            res = broker.submit_order(sym, qty, side,
                                      time_in_force="gtc" if is_crypto else "day")
            order_id = res.order_id
        log(sym, side, qty, price, verdict, notes.get(sym, ""), order_id)

    save_state(state_path, state)
    return rows
```

`scripts/run_session.py`:

```python
"""Run one trading session on the dedicated session-trader PAPER account.

    PYTHONPATH=. python scripts/run_session.py                 # dry run, auto session
    PYTHONPATH=. python scripts/run_session.py --execute       # submit paper orders
    PYTHONPATH=. python scripts/run_session.py --session open  # force a session
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from src.broker import AlpacaPaperBroker
from src.config import PROJECT_ROOT, load_broker_config
from src.intraday.groq_gate import review_trade
from src.intraday.limits import SessionLimits
from src.intraday.news import fetch_headlines
from src.intraday.prices import crypto_last_prices, load_daily_closes
from src.intraday.schedule import current_session
from src.intraday.session import run_session
from src.intraday.strategies import REGISTRY

STATE = PROJECT_ROOT / "portfolio" / "session_state.json"
LOG = PROJECT_ROOT / "portfolio" / "session_log.csv"


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--session")
    args = ap.parse_args()

    now = datetime.now(UTC)
    name = args.session or current_session(now)
    if name is None:
        print("No session due now; exiting.")
        return

    cfg = load_broker_config()
    broker = AlpacaPaperBroker(cfg)
    symbols = [s for spec in REGISTRY.values() if spec.active for s in spec.symbols]
    if not symbols:
        print("No active strategies (none passed the gate yet); exiting.")
        return
    stocks = [s for s in symbols if "/" not in s]
    crypto = [s for s in symbols if "/" in s]

    closes = load_daily_closes(symbols)
    prices = broker.get_last_prices(stocks) if stocks else {}
    prices |= crypto_last_prices(crypto, cfg.api_key_id, cfg.api_secret_key)
    headlines = fetch_headlines(symbols, cfg.api_key_id, cfg.api_secret_key)
    groq_key = os.environ.get("GROQ_API_KEY", "")

    rows = run_session(
        name=name, broker=broker, closes=closes, now_utc=now, limits=SessionLimits(),
        state_path=Path(STATE), log_path=Path(LOG), registry=REGISTRY,
        gate=lambda sym: review_trade(sym, headlines.get(sym, []), groq_key),
        prices=prices, dry_run=not args.execute,
    )
    for r in rows:
        print(r["session"], r["symbol"], r["side"], r["qty"], r["note"], r["news_action"])
    print(f"{len(rows)} action(s) in session {name!r} (dry_run={not args.execute})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Verify `PROJECT_ROOT` exists in `src/config.py`**

Run: `grep -n "PROJECT_ROOT" src/config.py | head -3`
Expected: a definition line. If absent, replace the import with `Path(__file__).resolve().parents[1]`.

- [ ] **Step 5: Run tests, expect 10 passed.** `PYTHONPATH=. python -m pytest tests/intraday -v`
- [ ] **Step 6: Commit**

```bash
git add src/intraday scripts/run_session.py tests/intraday
git commit -m "feat(intraday): session orchestrator, prices, and CLI"
```

---

### Task 6: Reporting

**Files:**
- Create: `src/intraday/report.py`, `scripts/weekly_report.py`, `tests/intraday/test_report.py`

**Interfaces:**
- Produces: `summarize(equity: pd.Series, bench: pd.Series) -> dict` with keys `return`, `bench_return`, `max_drawdown`, `sharpe`, `days`.

- [ ] **Step 1: Failing test**

```python
"""Tests for report statistics."""

from __future__ import annotations

import pandas as pd
import pytest

from src.intraday.report import summarize


def test_summarize_basic():
    idx = pd.date_range("2026-01-01", periods=4)
    eq = pd.Series([100.0, 110.0, 99.0, 105.0], index=idx)
    bench = pd.Series([100.0, 101.0, 102.0, 103.0], index=idx)
    s = summarize(eq, bench)
    assert s["return"] == pytest.approx(0.05)
    assert s["bench_return"] == pytest.approx(0.03)
    assert s["max_drawdown"] == pytest.approx(-0.10)
    assert s["days"] == 4
```

- [ ] **Step 2: Run, expect FAIL.** `PYTHONPATH=. python -m pytest tests/intraday/test_report.py -v`

- [ ] **Step 3: Implement** `src/intraday/report.py`:

```python
"""Plain performance statistics for the weekly report."""

from __future__ import annotations

import numpy as np
import pandas as pd


def summarize(equity: pd.Series, bench: pd.Series) -> dict:
    """Return, drawdown and Sharpe for an equity curve vs a benchmark curve."""
    r = equity.pct_change().dropna()
    std = r.std()
    return {
        "return": float(equity.iloc[-1] / equity.iloc[0] - 1),
        "bench_return": float(bench.iloc[-1] / bench.iloc[0] - 1),
        "max_drawdown": float((equity / equity.cummax() - 1).min()),
        "sharpe": float(r.mean() / std * np.sqrt(252)) if std and std > 0 else 0.0,
        "days": int(len(equity)),
    }
```

`scripts/weekly_report.py`:

```python
"""Write reports/weekly/<date>.md from Alpaca account history and the session log.

    PYTHONPATH=. python scripts/weekly_report.py
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import yfinance as yf

from src.broker import AlpacaPaperBroker
from src.config import PROJECT_ROOT, load_broker_config
from src.intraday.report import summarize


def main() -> None:
    broker = AlpacaPaperBroker(load_broker_config())
    hist = broker._request("GET", "/v2/account/portfolio/history",
                           params={"period": "3M", "timeframe": "1D"})
    idx = pd.to_datetime(hist["timestamp"], unit="s").normalize()
    equity = pd.Series(hist["equity"], index=idx).dropna()
    equity = equity[~equity.index.duplicated(keep="last")]
    spy = yf.download("SPY", start=equity.index[0], auto_adjust=True,
                      progress=False)["Close"].squeeze()
    spy = spy.reindex(equity.index).ffill().dropna()
    stats = summarize(equity.loc[spy.index], spy)

    log = PROJECT_ROOT / "portfolio" / "session_log.csv"
    trades = pd.read_csv(log) if log.exists() else pd.DataFrame()
    n_trades = int(trades["side"].isin(["buy", "sell"]).sum()) if len(trades) else 0
    today = datetime.now(UTC).date().isoformat()
    out = PROJECT_ROOT / "reports" / "weekly" / f"{today}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"# Session trader, week ending {today}\n\n"
        f"| Metric | Value |\n|---|---|\n"
        f"| Return | {stats['return']:.2%} |\n"
        f"| SPY buy-and-hold | {stats['bench_return']:.2%} |\n"
        f"| Max drawdown | {stats['max_drawdown']:.2%} |\n"
        f"| Sharpe (annualised) | {stats['sharpe']:.2f} |\n"
        f"| Trading days | {stats['days']} |\n"
        f"| Orders logged | {n_trades} |\n\n"
        "**Read with care:** under ~250 trading days a Sharpe ratio carries almost "
        "no information. Alpaca paper fills ignore slippage and market impact.\n"
    )
    print(out)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test, expect 1 passed.**
- [ ] **Step 5: Commit**

```bash
git add src/intraday/report.py scripts/weekly_report.py tests/intraday/test_report.py
git commit -m "feat(intraday): weekly performance report"
```

---

### Task 7: Run the gate, then deploy the workflow

**Files:**
- Create: `.github/workflows/sessions.yml`
- Modify: `src/intraday/strategies.py` (`active=` flags, only for strategies that pass), `research/daily_log.md` (append gate result), `requirements.txt` (nothing new; `requests`, `yfinance` already pinned), `.env.example` (add `GROQ_API_KEY=`)

- [ ] **Step 1: Run the pre-registered gate**

Run: `PYTHONPATH=. python scripts/run_session_gate.py`
Expected: three lines like `S1 {'sharpe': ..., 'max_drawdown': ..., 'passed': True/False, 'days': ...}`.

- [ ] **Step 2: Record results honestly.** Append to `research/daily_log.md` the date, the three result lines, and which strategies pass. Set `active=True` in `REGISTRY` **only** for passing strategies (add `True` as the last argument). Do not change any parameter. If none pass, stop here and tell the user; do not deploy.

- [ ] **Step 3: Add `.env.example` line** `GROQ_API_KEY=` under the Fred line, with a comment `# Free key from console.groq.com`.

- [ ] **Step 4: Write `.github/workflows/sessions.yml`**

```yaml
name: Trading sessions

on:
  schedule:
    # Fires at both the EDT and EST UTC hours; scripts/run_session.py only acts
    # when real Eastern time is within 25 min after a session time.
    - cron: "45 13,14 * * 1-5"   # open 09:45 ET
    - cron: "30 15,16 * * 1-5"   # late morning 11:30 ET
    - cron: "0 18,19 * * 1-5"    # afternoon 14:00 ET
    - cron: "45 19,20 * * 1-5"   # pre-close 15:45 ET
    - cron: "0 0,1 * * 2-6"      # evening crypto 20:00 ET
  workflow_dispatch:
    inputs:
      execute:
        description: "Submit paper orders (otherwise dry run)"
        default: "false"

permissions:
  contents: write

concurrency:
  group: sessions
  cancel-in-progress: false

jobs:
  session:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install --quiet -r requirements.txt
      - name: Run session
        env:
          ALPACA_API_KEY_ID: ${{ secrets.ALPACA_SESSION_KEY_ID }}
          ALPACA_API_SECRET_KEY: ${{ secrets.ALPACA_SESSION_SECRET_KEY }}
          ALPACA_BASE_URL: https://paper-api.alpaca.markets
          PAPER_TRADING_ONLY: "true"
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          EXECUTE: ${{ github.event_name == 'schedule' || inputs.execute == 'true' }}
          PYTHONPATH: .
        run: |
          if [ "$EXECUTE" = "true" ]; then python scripts/run_session.py --execute;
          else python scripts/run_session.py; fi
      - name: Save log and state
        run: |
          git config user.name "session-bot"
          git config user.email "session-bot@users.noreply.github.com"
          git add portfolio/session_log.csv portfolio/session_state.json || true
          git diff --cached --quiet || {
            git commit -m "auto: session log $(date -u +%F-%H%M)"
            git pull --rebase origin main
            git push
          }
```

- [ ] **Step 5: Dry-run locally once** with a throwaway `.env` for the NEW paper account: `PYTHONPATH=. python scripts/run_session.py --session open`
Expected: prints actions with `dry_run=True`, no orders placed.

- [ ] **Step 6: Commit and tell the user the manual steps**

```bash
git add -A .github/workflows/sessions.yml src/intraday research/daily_log.md .env.example
git commit -m "feat(intraday): deploy session workflow with gate-passing strategies"
```

User must do (cannot be automated): (1) create a **second Alpaca paper account** and generate its keys; (2) add GitHub secrets `ALPACA_SESSION_KEY_ID`, `ALPACA_SESSION_SECRET_KEY`, `GROQ_API_KEY` (free key at console.groq.com); (3) run the workflow once via "Run workflow" with `execute=false`, then let the schedule take over.

---

## Self-Review

- **Spec coverage:** paper only (Task 5 uses `load_broker_config`); 5 sessions (Task 3); GitHub cron (Task 7); Groq veto-only, fail safe (Task 4); universe ETF/stock/crypto (Task 2 registry); pre-registration and gate (Task 2, 7); limits and kill-switch (Task 1, 5); reporting (Task 5 log, Task 6 report). Gap noted: sector cap replaced by asset-class cap (stated in Global Constraints).
- **Placeholders:** none; all code shown.
- **Type consistency:** `StrategySpec(id, symbols, asset_class, capital_fraction, signal_fn, active)` used identically in Tasks 2, 5; `Verdict(action, reason)` in Tasks 4, 5; `run_session` keyword args match the CLI call and tests; `SessionLimits` fields match uses.
