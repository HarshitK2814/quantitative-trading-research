# Strategy Search & Ensemble — Implementation Plan (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Search hundreds-to-thousands of literature strategies with overfitting controls, then trade the survivors as one risk-parity ensemble on the Alpaca paper account before Mon 2026-11-23 open.

**Architecture:** New package `src/search/`. A point-in-time S&P 500 universe feeds a vectorised weights→returns engine. Strategy families yield weight frames from parameter grids. A selector applies train/valid/holdout + deflated Sharpe + perturbation. The ensemble builder freezes survivors to `portfolio/ensemble.json`, and `scripts/run_ensemble.py` trades them through the existing `AlpacaPaperBroker`. The existing S1/S2/O1/O2 session code stays; ensemble-owned symbols are excluded from it.

**Tech Stack:** Python 3.12, pandas, numpy, scipy, yfinance, pytest. Spec: `.plans/strategy-search-spec.md`.

**Phase 2 (separate plan, after Monday):** 30-min intraday families, options put-write/covered-call proxies, dashboard extension, weekly Gmail summary.

## Global Constraints
- Paper endpoint only (already enforced in `src/broker.py`).
- Gross exposure ≤ 100%, counting leveraged ETFs at notional × leverage.
- Kill switch: drawdown from peak ≤ -10% → scale 0.5; ≤ -15% → flat and latched until `killed` is reset by hand.
- Splits: train 2008-01-01..2020-12-31, validation 2021-01-01..2024-12-31, holdout 2025-01-01..latest (one touch).
- Costs: ETFs 5 bps, stocks 10 bps, crypto 25 bps per unit turnover; short borrow 1%/yr; delisting return -30%.
- Survivor rule: train Sharpe > 0 AND validation Sharpe (annualised) > SPY validation Sharpe AND DSR > 0.95 AND ±20% param perturbation keeps ≥ 50% of validation Sharpe AND holdout return > 0.
- Ensemble: inverse-vol (63-day), per-sleeve cap 25%, per-position cap 10%.
- Every trial is logged to `research/search_ledger.csv`. Pre-registered files are not edited.
- Run tests with `PYTHONPATH=. python -m pytest tests -q`.

## File map
| File | Responsibility |
|---|---|
| `src/search/universe.py` | Point-in-time S&P 500 membership, price/volume panel, liquidity mask |
| `src/search/engine.py` | Weights → net daily returns (lag, costs, borrow, delisting), gross cap, metrics |
| `src/search/families.py` | Strategy functions + `grid()` of trials |
| `src/search/select.py` | Split stats, DSR filter, perturbation, holdout, de-dup |
| `src/search/ensemble.py` | Inverse-vol combine, kill-switch scale, latest targets |
| `scripts/run_search.py` | Runs the search; writes ledger, report, `portfolio/ensemble.json` |
| `scripts/run_ensemble.py` | Live: targets → paper orders |
| `scripts/run_session.py`, `src/intraday/session.py` | Exclude ensemble symbols; retire failed S1/S2 |
| `scripts/run_session_local.ps1` | Call `run_ensemble.py` at the `open` session |

---

### Task 1: Universe (point-in-time S&P 500 + panel)

**Files:** Create `src/search/__init__.py` (empty), `src/search/universe.py`, `tests/search/__init__.py` (empty), `tests/search/test_universe.py`

**Interfaces — Produces:**
- `sp500_membership(start: str = "2007-01-01", read_html=pd.read_html, today=None) -> pd.DataFrame` (bool, business days × yfinance tickers)
- `load_panel(tickers: list[str], start: str = "2007-01-01", cache_dir: Path = Path("data/search")) -> tuple[pd.DataFrame, pd.DataFrame]` (close, volume)
- `top_liquid(close, volume, members, n: int = 150) -> pd.DataFrame` (bool)
- `ETFS: list[str]`, `CRYPTO: list[str]`, `LEVERAGE: dict[str, float]`

- [ ] **Step 1: Failing tests**

```python
# tests/search/test_universe.py
import pandas as pd
from src.search.universe import sp500_membership, top_liquid


def _fake_html(url):
    cur = pd.DataFrame({"Symbol": ["AAA", "BRK.B"]})
    ch = pd.DataFrame([["2020-06-01", "AAA", "A co", "OLD", "Old co", "x"]])
    return [cur, ch]


def test_membership_reconstructs_history():
    m = sp500_membership("2020-05-25", read_html=_fake_html, today="2020-06-05")
    assert m.loc["2020-05-29", "OLD"] and not m.loc["2020-05-29", "AAA"]
    assert m.loc["2020-06-01", "AAA"] and not m.loc["2020-06-01", "OLD"]
    assert m["BRK-B"].all()


def test_top_liquid_ranks_by_dollar_volume():
    idx = pd.bdate_range("2020-01-01", periods=80)
    close = pd.DataFrame({"A": 10.0, "B": 10.0, "C": 10.0}, index=idx)
    vol = pd.DataFrame({"A": 100.0, "B": 300.0, "C": 200.0}, index=idx)
    mem = pd.DataFrame(True, index=idx, columns=close.columns)
    mem["C"] = False
    t = top_liquid(close, vol, mem, n=1)
    assert t.iloc[-1].to_dict() == {"A": False, "B": True, "C": False}
```

- [ ] **Step 2:** Run `PYTHONPATH=. python -m pytest tests/search/test_universe.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# src/search/universe.py
"""Point-in-time S&P 500 universe and price panel (reduces survivorship bias)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
ETFS = ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY",
        "XLU", "XLB", "XLRE", "XLC", "VNQ", "GLD", "SLV", "TLT", "IEF", "SHY", "LQD",
        "HYG", "TIP", "DBC", "USO", "UUP", "EFA", "EEM", "VGK", "EWJ", "MTUM", "USMV",
        "QUAL", "VLUE", "SH", "PSQ", "SSO", "QLD", "SDS", "SQQQ", "TQQQ", "TMF"]
CRYPTO = ["BTC-USD", "ETH-USD"]
LEVERAGE = {"SSO": 2, "QLD": 2, "SDS": 2, "SQQQ": 3, "TQQQ": 3, "TMF": 3}


def _yf(sym: str) -> str:
    return str(sym).strip().replace(".", "-")


def sp500_membership(start="2007-01-01", read_html=pd.read_html, today=None) -> pd.DataFrame:
    tables = read_html(WIKI)
    current = {_yf(s) for s in tables[0]["Symbol"]}
    ch = tables[1].iloc[:, :6].copy()
    ch.columns = ["date", "added", "an", "removed", "rn", "reason"]
    ch["date"] = pd.to_datetime(ch["date"], errors="coerce")
    ch = ch.dropna(subset=["date"]).sort_values("date", ascending=False)
    days = pd.bdate_range(start, pd.Timestamp(today) if today else pd.Timestamp.today().normalize())
    members, snaps, j, rows = set(current), [], 0, list(ch.itertuples())
    for d in days[::-1]:
        while j < len(rows) and rows[j].date > d:
            if isinstance(rows[j].added, str) and rows[j].added.strip():
                members.discard(_yf(rows[j].added))
            if isinstance(rows[j].removed, str) and rows[j].removed.strip():
                members.add(_yf(rows[j].removed))
            j += 1
        snaps.append(frozenset(members))
    snaps.reverse()
    cols = sorted(set().union(*snaps))
    pos = {c: k for k, c in enumerate(cols)}
    data = np.zeros((len(days), len(cols)), dtype=bool)
    for r, s in enumerate(snaps):
        data[r, [pos[t] for t in s]] = True
    return pd.DataFrame(data, index=days, columns=cols)


def load_panel(tickers, start="2007-01-01", cache_dir=Path("data/search")):
    import yfinance as yf
    cache_dir.mkdir(parents=True, exist_ok=True)
    cpath, vpath = cache_dir / "close.parquet", cache_dir / "volume.parquet"
    today = pd.Timestamp.today().normalize()
    if cpath.exists() and (today - pd.Timestamp(cpath.stat().st_mtime, unit="s")).days < 1:
        return pd.read_parquet(cpath), pd.read_parquet(vpath)
    closes, vols = [], []
    for i in range(0, len(tickers), 100):
        d = yf.download(tickers[i:i + 100], start=start, auto_adjust=True,
                        progress=False, threads=True)
        closes.append(d["Close"])
        vols.append(d["Volume"])
    close = pd.concat(closes, axis=1).sort_index()
    vol = pd.concat(vols, axis=1).sort_index()
    close = close.loc[:, ~close.columns.duplicated()]
    vol = vol.loc[:, ~vol.columns.duplicated()]
    close.to_parquet(cpath)
    vol.to_parquet(vpath)
    return close, vol


def top_liquid(close, volume, members, n=150):
    dv = (close * volume).rolling(63, min_periods=20).median()
    dv = dv.where(members.reindex_like(dv).fillna(False).astype(bool))
    rank = dv.rank(axis=1, ascending=False)
    return (rank <= n).fillna(False)
```

- [ ] **Step 4:** Rerun test → PASS.
- [ ] **Step 5:** `git add src/search tests/search && git commit -m "search: point-in-time S&P 500 universe"`

---

### Task 2: Engine

**Files:** Create `src/search/engine.py`, `tests/search/test_engine.py`

**Interfaces — Produces:**
- `Costs(bps=10.0, borrow_annual=0.01, delist_return=-0.30)`
- `cost_table(columns) -> pd.Series` (5 ETFs, 10 stocks, 25 crypto)
- `cap_gross(w: pd.DataFrame, cap: float = 1.0) -> pd.DataFrame` (uses `LEVERAGE`)
- `run_weights(w, close, costs=Costs(), bps: pd.Series | None = None) -> pd.Series`
- `metrics(r: pd.Series) -> dict` with keys `sharpe` (annual), `sharpe_d` (daily), `ret_ann`, `total`, `max_dd`, `n`

- [ ] **Step 1: Failing tests**

```python
# tests/search/test_engine.py
import numpy as np
import pandas as pd
from src.search.engine import Costs, cap_gross, metrics, run_weights

IDX = pd.bdate_range("2020-01-01", periods=5)


def test_one_bar_lag_and_cost():
    close = pd.DataFrame({"A": [100, 110, 121, 121, 121.0]}, index=IDX)
    w = pd.DataFrame({"A": [1.0, 1, 1, 1, 1]}, index=IDX)
    r = run_weights(w, close, Costs(bps=10, borrow_annual=0))
    assert abs(r.iloc[0] + 0.001) < 1e-12        # entry cost only, no return
    assert abs(r.iloc[1] - 0.10) < 1e-12          # earns day-2 move


def test_short_pays_borrow_and_delisting_hits():
    close = pd.DataFrame({"A": [100, 100, np.nan, np.nan, np.nan],
                          "B": [10, 10, 10, 10, 10.0]}, index=IDX)
    w = pd.DataFrame({"A": [1.0, 1, 1, 1, 1], "B": [-1.0] * 5}, index=IDX)
    r = run_weights(w, close, Costs(bps=0, borrow_annual=0.252, delist_return=-0.3))
    assert abs(r.iloc[2] - (-0.3 - 0.001)) < 1e-9
    assert abs(r.iloc[3] + 0.001) < 1e-9          # A gone, only borrow on B


def test_cap_gross_counts_leverage():
    w = pd.DataFrame({"TQQQ": [0.5], "SPY": [0.5]})
    out = cap_gross(w)
    assert abs(out.iloc[0]["TQQQ"] * 3 + out.iloc[0]["SPY"] - 1.0) < 1e-12


def test_metrics_drawdown():
    m = metrics(pd.Series([0.1, -0.5, 0.2]))
    assert abs(m["max_dd"] + 0.5) < 1e-12
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement**

```python
# src/search/engine.py
"""Vectorised weights -> net daily returns. Weights at close t earn t+1."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.search.universe import CRYPTO, ETFS, LEVERAGE


@dataclass(frozen=True)
class Costs:
    bps: float = 10.0
    borrow_annual: float = 0.01
    delist_return: float = -0.30


def cost_table(columns) -> pd.Series:
    return pd.Series([5.0 if c in ETFS else 25.0 if c in CRYPTO else 10.0 for c in columns],
                     index=list(columns))


def cap_gross(w: pd.DataFrame, cap: float = 1.0) -> pd.DataFrame:
    lev = pd.Series({c: LEVERAGE.get(c, 1.0) for c in w.columns})
    gross = (w.abs() * lev).sum(axis=1)
    scale = (cap / gross).clip(upper=1.0).fillna(1.0)
    return w.mul(scale, axis=0)


def run_weights(w, close, costs=Costs(), bps=None) -> pd.Series:
    w = w.reindex(index=close.index, columns=close.columns).fillna(0.0)
    w = w.where(close.notna(), 0.0)
    r = close.pct_change(fill_method=None)
    end = close.index[-1]
    for col, lv in close.apply(pd.Series.last_valid_index).items():
        if lv is not None and (end - lv).days > 7:
            k = close.index.get_loc(lv)
            if k + 1 < len(close.index):
                r.iloc[k + 1, close.columns.get_loc(col)] = costs.delist_return
    r = r.fillna(0.0)
    held = w.shift(1).fillna(0.0)
    b = bps.reindex(close.columns).fillna(costs.bps) if bps is not None \
        else pd.Series(costs.bps, index=close.columns)
    trade = w.diff().abs()
    trade.iloc[0] = w.iloc[0].abs()
    cost = (trade * b / 1e4).sum(axis=1)
    borrow = held.clip(upper=0).abs().sum(axis=1) * costs.borrow_annual / 252
    return (held * r).sum(axis=1) - cost - borrow


def metrics(r: pd.Series) -> dict:
    r = r.dropna()
    sd = r.std()
    eq = (1 + r).cumprod()
    sd_ok = bool(sd > 0)
    return {"sharpe": float(r.mean() / sd * np.sqrt(252)) if sd_ok else 0.0,
            "sharpe_d": float(r.mean() / sd) if sd_ok else 0.0,
            "ret_ann": float(r.mean() * 252),
            "total": float(eq.iloc[-1] - 1) if len(r) else 0.0,
            "max_dd": float((eq / eq.cummax() - 1).min()) if len(r) else 0.0,
            "n": int(len(r))}
```

Note: in the delisting test, day index 2 is the first NaN for A, so A earns -0.3. Borrow on B is 1 × 0.252/252 = 0.001.

- [ ] **Step 4:** Rerun → PASS.
- [ ] **Step 5:** Commit `search: weights engine with costs, borrow, delisting`.

---

### Task 3: Strategy families + grid

**Files:** Create `src/search/families.py`, `tests/search/test_families.py`

**Interfaces — Consumes:** `ETFS`, `CRYPTO` from universe.
**Produces:**
- `Ctx(close: pd.DataFrame, members: pd.DataFrame | None, liquid: pd.DataFrame | None)`
- `Trial(name: str, family: str, params: dict)`, with `Trial.weights(ctx) -> pd.DataFrame`
- `FAMILIES: dict[str, Callable[[Ctx, ...], pd.DataFrame]]`
- `grid() -> list[Trial]`

All weights use data through close t only (the engine adds the lag). Universe keys in params: `"etf16"`, `"sectors"`, `"etf_all"`, `"stocks"` (liquid mask), `"crypto"`, `"s1"` (S1 symbols), `"s2"` (S2 symbols).

- [ ] **Step 1: Failing tests**

```python
# tests/search/test_families.py
import numpy as np
import pandas as pd
from src.search.families import Ctx, FAMILIES, grid

IDX = pd.bdate_range("2015-01-01", periods=600)


def _ctx():
    rng = np.random.default_rng(0)
    cols = ["SPY", "QQQ", "XLK", "XLF", "XLE", "XLV", "TLT", "GLD", "SH"]
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, .01, (600, len(cols))), 0)),
                         index=IDX, columns=cols)
    return Ctx(close=close, members=None, liquid=None)


def test_no_lookahead_every_family():
    ctx = _ctx()
    for t in [t for t in grid() if t.params.get("universe") not in ("stocks", "crypto", "s2")][:60]:
        w1 = t.weights(ctx)
        c2 = ctx.close.copy()
        c2.iloc[400:] *= 1.5                      # change the future only
        w2 = t.weights(Ctx(c2, None, None))
        pd.testing.assert_frame_equal(w1.iloc[:400], w2.iloc[:400], check_dtype=False,
                                      obj=t.name)


def test_grid_is_large_and_unique():
    g = grid()
    assert len(g) >= 500
    assert len({t.name for t in g}) == len(g)
    assert {t.family for t in g} >= set(FAMILIES)
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement**

```python
# src/search/families.py
"""Literature strategy families. Each returns target weights using data through t."""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

import numpy as np
import pandas as pd

from src.search.universe import CRYPTO

ETF16 = ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY",
         "XLU", "VNQ", "GLD", "SLV", "TLT"]
SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB"]
ETF_ALL = ETF16 + ["IEF", "SHY", "LQD", "HYG", "TIP", "DBC", "EFA", "EEM", "XLB"]
S1 = ["SPY", "QQQ", "XLK", "XLF", "XLE", "XLV"]
S2 = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]
RISK_OFF = {"bonds": ["TLT", "IEF"], "gold_bonds": ["TLT", "GLD"], "inverse": ["SH"],
            "cash": []}


@dataclass(frozen=True)
class Ctx:
    close: pd.DataFrame
    members: pd.DataFrame | None
    liquid: pd.DataFrame | None


def _cols(ctx, universe):
    fixed = {"etf16": ETF16, "sectors": SECTORS, "etf_all": ETF_ALL, "s1": S1, "s2": S2,
             "crypto": CRYPTO}.get(universe)
    if fixed is not None:
        return [c for c in fixed if c in ctx.close.columns]
    return [c for c in ctx.liquid.columns if c in ctx.close.columns]  # "stocks"


def _mask(ctx, universe, cols):
    if universe == "stocks" and ctx.liquid is not None:
        return ctx.liquid.reindex(index=ctx.close.index, columns=cols).fillna(False).astype(bool)
    return ctx.close[cols].notna()


def _month_ends(idx):
    """Calendar rule (next business day is a new month): safe on a live, partial month."""
    nxt = idx + pd.offsets.BDay(1)
    return idx[nxt.month != idx.month]


def _week_ends(idx):
    nxt = idx + pd.offsets.BDay(1)
    return idx[nxt.to_period("W") != idx.to_period("W")]


def _hold(w_rebal, idx):
    return w_rebal.reindex(idx).ffill().fillna(0.0)


def sma_trend(ctx, universe, fast, slow):
    cols = _cols(ctx, universe)
    c = ctx.close[cols]
    f, s = c.rolling(fast).mean(), c.rolling(slow).mean()
    return ((c > s) & (f > s)).astype(float) / len(cols)


def tsmom(ctx, universe, lookback, long_short, vol_target):
    cols = _cols(ctx, universe)
    c = ctx.close[cols]
    m = c / c.shift(lookback) - 1
    sig = np.sign(m) if long_short else (m > 0).astype(float)
    if vol_target:
        vol = c.pct_change(fill_method=None).rolling(63).std() * np.sqrt(252)
        sig = sig * (0.15 / vol).clip(upper=1.0)
    return sig.fillna(0.0) / len(cols)


def _rank_book(score, mask, dates, top, long_short):
    w = pd.DataFrame(0.0, index=dates, columns=score.columns)
    for d in dates:
        s = score.loc[d][mask.loc[d]].dropna()
        if len(s) < 2 * top:
            continue
        side = 0.5 if long_short else 1.0
        w.loc[d, s.nlargest(top).index] = side / top
        if long_short:
            w.loc[d, s.nsmallest(top).index] = -side / top
    return w


def xs_mom(ctx, universe, lookback, skip, top, long_short):
    cols = _cols(ctx, universe)
    c = ctx.close[cols]
    score = c.shift(skip) / c.shift(lookback) - 1
    dates = _month_ends(c.index)
    return _hold(_rank_book(score, _mask(ctx, universe, cols), dates, top, long_short), c.index)


def reversal(ctx, universe, lookback, top):
    cols = _cols(ctx, universe)
    c = ctx.close[cols]
    score = -(c / c.shift(lookback) - 1)  # losers score high
    dates = _week_ends(c.index)
    return _hold(_rank_book(score, _mask(ctx, universe, cols), dates, top, True), c.index)


def low_vol(ctx, universe, window, top):
    cols = _cols(ctx, universe)
    c = ctx.close[cols]
    score = -c.pct_change(fill_method=None).rolling(window).std()
    dates = _month_ends(c.index)
    return _hold(_rank_book(score, _mask(ctx, universe, cols), dates, top, False), c.index)


def _rsi(c, n=2):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn)).fillna(50.0)


def rsi2(ctx, universe, entry, exit_, sma):
    cols = _cols(ctx, universe)
    c = ctx.close[cols]
    rsi, trend = _rsi(c).values, (c > c.rolling(sma).mean()).values
    mask = _mask(ctx, universe, cols).values
    held = np.zeros(len(cols))
    out = np.zeros(c.shape)
    for i in range(len(c)):
        enter = (held == 0) & (rsi[i] < entry) & trend[i] & mask[i]
        leave = (held == 1) & ((rsi[i] > exit_) | ~mask[i])
        held = np.where(enter, 1.0, np.where(leave, 0.0, held))
        out[i] = held
    w = pd.DataFrame(out, index=c.index, columns=cols)
    return w / max(10, len(cols) // 10)  # at most ~10% per name


def pairs(ctx, universe, formation, n_pairs, z_entry):
    cols = _cols(ctx, universe)
    lp = np.log(ctx.close[cols])
    idx = lp.index
    w = pd.DataFrame(0.0, index=idx, columns=cols)
    for start in range(formation, len(idx), 126):
        form = lp.iloc[start - formation:start].dropna(axis=1)
        if form.shape[1] < 4:
            continue
        norm = form - form.mean()
        names = list(norm.columns)
        corr = norm.diff().corr().values
        np.fill_diagonal(corr, -1)
        cand = sorted(((corr[i, j], names[i], names[j]) for i in range(len(names))
                       for j in range(i + 1, len(names))), reverse=True)[:n_pairs]
        trade = lp.iloc[start:start + 126]
        for _, a, b in cand:
            spread_hist = form[a] - form[b]
            mu, sd = spread_hist.mean(), spread_hist.std()
            if not sd > 0:
                continue
            z = ((trade[a] - trade[b]) - mu) / sd
            pos, state = [], 0.0
            for zz in z.values:
                if state == 0 and zz > z_entry:
                    state = -1.0
                elif state == 0 and zz < -z_entry:
                    state = 1.0
                elif state != 0 and abs(zz) < 0.25:
                    state = 0.0
                pos.append(state)
            pos = pd.Series(pos, index=trade.index) * 0.5 / n_pairs
            w.loc[trade.index, a] += pos
            w.loc[trade.index, b] -= pos
    return w


def regime(ctx, sma, risk_off):
    c = ctx.close
    on = c["SPY"] > c["SPY"].rolling(sma).mean()
    eq = [x for x in S1 if x in c.columns]
    off = [x for x in RISK_OFF[risk_off] if x in c.columns]
    w = pd.DataFrame(0.0, index=c.index, columns=sorted(set(eq + off)))
    w.loc[on, eq] = 1.0 / len(eq)
    if off:
        w.loc[~on, off] = 1.0 / len(off)
    return w


def turn_of_month(ctx, before, after):
    idx = ctx.close.index
    pos = pd.Series(0.0, index=idx)
    me = set(_month_ends(idx))
    loc = [i for i, d in enumerate(idx) if d in me]
    for i in loc:
        pos.iloc[max(0, i - before):min(len(idx), i + after)] = 1.0
    # weight set at close t is held over t+1, so shift one bar earlier
    return pd.DataFrame({"SPY": pos.shift(-1).fillna(0.0)})


FAMILIES = {"sma_trend": sma_trend, "tsmom": tsmom, "xs_mom": xs_mom,
            "reversal": reversal, "low_vol": low_vol, "rsi2": rsi2, "pairs": pairs,
            "regime": regime, "turn_of_month": turn_of_month}


@dataclass(frozen=True)
class Trial:
    name: str
    family: str
    params: dict = field(hash=False)

    def weights(self, ctx: Ctx) -> pd.DataFrame:
        return FAMILIES[self.family](ctx, **self.params)


def _t(family, **p):
    return Trial(family + ":" + ",".join(f"{k}={v}" for k, v in sorted(p.items())), family, p)


def grid() -> list[Trial]:
    g = []
    for u, f, s in product(["etf16", "sectors", "etf_all", "s1", "crypto"],
                           [5, 10, 20, 50, 100], [50, 100, 150, 200, 250]):
        if f < s:
            g.append(_t("sma_trend", universe=u, fast=f, slow=s))
    for u, lb, ls, vt in product(["etf16", "sectors", "etf_all", "s1", "crypto"],
                                 [21, 63, 126, 189, 252], [False, True], [False, True]):
        g.append(_t("tsmom", universe=u, lookback=lb, long_short=ls, vol_target=vt))
    for lb, sk, top, ls in product([63, 126, 189, 252], [0, 21], [10, 20, 30, 50], [False, True]):
        g.append(_t("xs_mom", universe="stocks", lookback=lb, skip=sk, top=top, long_short=ls))
    for u, lb, sk, top in product(["etf16", "etf_all", "sectors"], [63, 126, 189, 252],
                                  [0, 21], [2, 3, 5]):
        g.append(_t("xs_mom", universe=u, lookback=lb, skip=sk, top=top, long_short=False))
    for u, lb, top in product(["stocks", "etf_all"], [3, 5, 10, 21], [5, 10, 20, 50]):
        g.append(_t("reversal", universe=u, lookback=lb, top=top))
    for w_, top in product([21, 63, 126, 252], [10, 20, 50, 100]):
        g.append(_t("low_vol", universe="stocks", window=w_, top=top))
    for u, en, ex, sm in product(["stocks", "s2", "etf16", "sectors"], [5, 10, 15, 20],
                                 [50, 70, 90], [100, 200]):
        g.append(_t("rsi2", universe=u, entry=en, exit_=ex, sma=sm))
    for u, fm, n, z in product(["etf_all", "sectors"], [126, 252], [3, 5, 10], [1.5, 2.0, 2.5]):
        g.append(_t("pairs", universe=u, formation=fm, n_pairs=n, z_entry=z))
    for sm, ro in product([50, 100, 150, 200, 250], list(RISK_OFF)):
        g.append(_t("regime", sma=sm, risk_off=ro))
    for b, a in product([0, 1, 2, 3], [1, 2, 3, 4, 5]):
        g.append(_t("turn_of_month", before=b, after=a))
    return g
```

- [ ] **Step 4:** Rerun → PASS. If `len(g) < 500`, the test is wrong about the grid; count it and fix the test to the real count (do not pad the grid).
- [ ] **Step 5:** Commit `search: strategy families and parameter grid`.

---

### Task 4: Selection + search runner

**Files:** Create `src/search/select.py`, `scripts/run_search.py`, `tests/search/test_select.py`

**Interfaces — Consumes:** `run_weights`, `metrics`, `cost_table`, `cap_gross`, `Trial`, `Ctx`, `grid`, `deflated_sharpe_ratio` (`src/overfitting.py`, daily Sharpe, as in `scripts/run_ledger_dsr.py`).
**Produces:**
- `SPLITS = {"train": ("2008-01-01","2020-12-31"), "valid": ("2021-01-01","2024-12-31"), "hold": ("2025-01-01", None)}`
- `split_stats(r: pd.Series) -> dict[str, dict]`
- `add_dsr(table: pd.DataFrame) -> pd.DataFrame` (adds `dsr`, using `valid_sharpe_d`, `n_trials=len(table)`)
- `perturb(trial: Trial) -> list[Trial]` (each numeric non-bool param × 0.8 and × 1.2, rounded ints)
- `dedup(returns: dict[str, pd.Series], order: list[str], max_corr=0.9) -> list[str]`
- `portfolio/ensemble.json`: `{"created": iso, "trials": [{"name","family","params"}], "retire": ["S1"|"S2"...], "n_trials": int}`

- [ ] **Step 1: Failing tests**

```python
# tests/search/test_select.py
import numpy as np
import pandas as pd
from src.search.families import Trial
from src.search.select import add_dsr, dedup, perturb, split_stats


def test_split_stats_keys():
    idx = pd.bdate_range("2019-01-01", "2025-06-30")
    r = pd.Series(np.random.default_rng(1).normal(0, .01, len(idx)), index=idx)
    s = split_stats(r)
    assert set(s) == {"train", "valid", "hold"} and s["valid"]["n"] > 900


def test_dsr_penalises_many_trials():
    t = pd.DataFrame({"valid_sharpe_d": [0.08] + [0.0] * 9, "valid_n": 1000,
                      "valid_skew": 0.0, "valid_kurt": 3.0})
    few = add_dsr(t.iloc[:2].copy())["dsr"].iloc[0]
    many = add_dsr(t.copy())["dsr"].iloc[0]
    assert many < few


def test_perturb_scales_numeric_params_only():
    t = Trial("x", "tsmom", {"universe": "s1", "lookback": 100, "long_short": True,
                             "vol_target": False})
    vals = sorted(p.params["lookback"] for p in perturb(t))
    assert vals == [80, 120]


def test_dedup_drops_correlated():
    a = pd.Series(np.random.default_rng(2).normal(size=300))
    out = dedup({"a": a, "b": a * 2, "c": -a.shift(1).fillna(0)}, ["a", "b", "c"])
    assert out == ["a", "c"]
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement `src/search/select.py`**

```python
"""Anti-overfitting selection: splits, deflated Sharpe, perturbation, de-dup."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, skew

from src.overfitting import deflated_sharpe_ratio
from src.search.engine import metrics
from src.search.families import Trial

SPLITS = {"train": ("2008-01-01", "2020-12-31"), "valid": ("2021-01-01", "2024-12-31"),
          "hold": ("2025-01-01", None)}


def split_stats(r: pd.Series) -> dict:
    out = {}
    for k, (a, b) in SPLITS.items():
        x = r.loc[a:b].dropna()
        m = metrics(x)
        m["skew"] = float(skew(x)) if len(x) > 2 else 0.0
        m["kurt"] = float(kurtosis(x, fisher=False)) if len(x) > 3 else 3.0
        out[k] = m
    return out


def add_dsr(table: pd.DataFrame) -> pd.DataFrame:
    var = float(np.var(table["valid_sharpe_d"], ddof=1)) if len(table) > 1 else 0.0
    var = max(var, 1e-8)
    table["dsr"] = [deflated_sharpe_ratio(s, int(n), len(table), var, skewness=sk, kurtosis=ku)
                    for s, n, sk, ku in zip(table["valid_sharpe_d"], table["valid_n"],
                                            table["valid_skew"], table["valid_kurt"],
                                            strict=True)]
    return table


def perturb(trial: Trial) -> list[Trial]:
    out = []
    for k, v in trial.params.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        for f in (0.8, 1.2):
            nv = type(v)(round(v * f)) if isinstance(v, int) else v * f
            if nv == v:
                continue
            p = dict(trial.params, **{k: nv})
            out.append(Trial(f"{trial.name}|{k}x{f}", trial.family, p))
    return out


def dedup(returns: dict, order: list[str], max_corr: float = 0.9) -> list[str]:
    keep = []
    for n in order:
        if all(abs(returns[n].corr(returns[k])) <= max_corr for k in keep):
            keep.append(n)
    return keep
```

- [ ] **Step 4:** Rerun tests → PASS. Commit `search: selection rules`.

- [ ] **Step 5: Write `scripts/run_search.py`**

```python
"""Run the strategy search (exploratory track; see .plans/strategy-search-spec.md).

    PYTHONPATH=. python scripts/run_search.py [--limit N]
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.search.engine import cap_gross, cost_table, metrics, run_weights
from src.search.families import S2, Ctx, Trial, grid
from src.search.select import SPLITS, add_dsr, dedup, perturb, split_stats
from src.search.universe import CRYPTO, ETFS, load_panel, sp500_membership, top_liquid

LEDGER = Path("research/search_ledger.csv")
REPORT = Path("research/strategy_search.md")
OUT = Path("portfolio/ensemble.json")
LIVE_MAP = {"S1": "sma_trend:fast=50,slow=200,universe=s1",
            "S2": "rsi2:entry=10,exit_=70,sma=200,universe=s2",
            "H1": "xs_mom:long_short=False,lookback=126,skip=21,top=5,universe=etf16"}


def evaluate(trial: Trial, ctx: Ctx, bps) -> pd.Series:
    w = cap_gross(trial.weights(ctx).fillna(0.0))
    return run_weights(w, ctx.close[w.columns], bps=bps[w.columns])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    members = sp500_membership()
    close, vol = load_panel(sorted(set(members.columns) | set(ETFS) | set(CRYPTO) | set(S2)))
    close = close.loc["2007-01-01":]
    liquid = top_liquid(close, vol, members.reindex(close.index).ffill().fillna(False), n=150)
    ctx = Ctx(close=close, members=members, liquid=liquid)
    bps = cost_table(close.columns)
    spy = split_stats(close["SPY"].pct_change(fill_method=None).fillna(0.0))
    trials = grid()[: args.limit]
    rows, rets = [], {}
    for i, t in enumerate(trials):
        try:
            r = evaluate(t, ctx, bps)
        except Exception as exc:  # noqa: BLE001 - log and continue
            print("FAIL", t.name, exc)
            continue
        s = split_stats(r)
        rets[t.name] = r
        rows.append({"name": t.name, "family": t.family, "params": json.dumps(t.params),
                     **{f"{k}_{m}": v for k, d in s.items() for m, v in d.items()}})
        if i % 50 == 0:
            print(f"{i}/{len(trials)}")
    tab = add_dsr(pd.DataFrame(rows))
    tab["pass_basic"] = ((tab["train_sharpe"] > 0) &
                         (tab["valid_sharpe"] > spy["valid"]["sharpe"]) & (tab["dsr"] > 0.95))
    finalists = []
    by_name = {t.name: t for t in trials}
    for name in tab.loc[tab["pass_basic"]].sort_values("valid_sharpe", ascending=False)["name"]:
        base = tab.set_index("name").loc[name, "valid_sharpe"]
        neigh = [metrics(evaluate(p, ctx, bps).loc[SPLITS["valid"][0]:SPLITS["valid"][1]])["sharpe"]
                 for p in perturb(by_name[name])]
        if all(n >= 0.5 * base for n in neigh):
            finalists.append(name)
    tab["robust"] = tab["name"].isin(finalists)
    finalists = dedup({n: rets[n].loc[SPLITS["valid"][0]:SPLITS["valid"][1]] for n in finalists},
                      finalists)
    # one-touch holdout, finalists only
    survivors = [n for n in finalists
                 if tab.set_index("name").loc[n, "hold_total"] > 0]
    tab["survivor"] = tab["name"].isin(survivors)
    tab.to_csv(LEDGER, mode="a", header=not LEDGER.exists(), index=False)
    retire = [k for k, v in LIVE_MAP.items() if v not in survivors]
    OUT.write_text(json.dumps({
        "created": datetime.now(UTC).isoformat(), "n_trials": len(tab), "retire": retire,
        "trials": [{"name": n, "family": by_name[n].family, "params": by_name[n].params}
                   for n in survivors]}, indent=2))
    write_report(tab, spy, survivors, retire)


def write_report(tab, spy, survivors, retire):
    top = tab.sort_values("valid_sharpe", ascending=False).head(20)
    fam = tab.groupby("family").agg(trials=("name", "size"),
                                    best_valid=("valid_sharpe", "max"),
                                    passed=("pass_basic", "sum"))
    lines = [
        "# Strategy search (exploratory track)", "",
        f"Run {datetime.now(UTC):%Y-%m-%d}. **{len(tab)} trials.** Not pre-registered; "
        "every trial is in `research/search_ledger.csv`.", "",
        f"SPY Sharpe: train {spy['train']['sharpe']:.2f}, valid {spy['valid']['sharpe']:.2f}, "
        f"holdout {spy['hold']['sharpe']:.2f}.", "",
        "## By family", "", fam.to_markdown(), "",
        "## Top 20 by validation Sharpe", "",
        top[["name", "train_sharpe", "valid_sharpe", "valid_max_dd", "dsr", "robust",
             "survivor"]].to_markdown(index=False), "",
        f"## Survivors ({len(survivors)})", "", *[f"- `{s}`" for s in survivors], "",
        f"Retired live sleeves: {retire or 'none'}.", "",
        "Limits: survivorship reduced (point-in-time membership, -30% delisting) but not "
        "removed; delisted names missing from yfinance are absent. DSR uses all trials.",
    ]
    REPORT.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6:** Smoke test: `PYTHONPATH=. python scripts/run_search.py --limit 30` → prints progress and writes all three files. Delete the smoke outputs (`git checkout`/remove), then run the full search in the background: `PYTHONPATH=. python scripts/run_search.py`.
- [ ] **Step 7:** Commit code + `research/strategy_search.md`, `research/search_ledger.csv`, `portfolio/ensemble.json`: `search: run full strategy search`.

---

### Task 5: Ensemble + live runner

**Files:** Create `src/search/ensemble.py`, `scripts/run_ensemble.py`, `tests/search/test_ensemble.py`

**Interfaces — Consumes:** `Trial`, `Ctx`, `run_weights`, `cap_gross`, `cost_table`; broker `get_account()`, `get_positions()` (keys like `BRK.B`, `BTCUSD`), `get_last_prices(list)`, `submit_order(symbol, qty, side, time_in_force=..., client_order_id=...)`, `is_market_open()`.
**Produces:**
- `combine(sleeve_w: dict[str, pd.DataFrame], sleeve_r: dict[str, pd.Series], cap=0.25) -> pd.Series` (latest target weights, yfinance tickers)
- `kill_scale(equity: float, state: dict) -> float` (updates `state["peak"]`, `state["killed"]`)
- `to_alpaca(sym: str) -> str`

- [ ] **Step 1: Failing tests**

```python
# tests/search/test_ensemble.py
import numpy as np
import pandas as pd
from src.search.ensemble import combine, kill_scale, to_alpaca

IDX = pd.bdate_range("2024-01-01", periods=100)


def test_inverse_vol_and_caps():
    rng = np.random.default_rng(3)
    r = {"lo": pd.Series(rng.normal(0, .005, 100), index=IDX),
         "hi": pd.Series(rng.normal(0, .02, 100), index=IDX)}
    w = {"lo": pd.DataFrame({"SPY": [1.0] * 100}, index=IDX),
         "hi": pd.DataFrame({"QQQ": [1.0] * 100}, index=IDX)}
    t = combine(w, r, cap=0.25)
    assert t["SPY"] <= 0.25 + 1e-12 and t["QQQ"] < t["SPY"]


def test_kill_switch_levels_and_latch():
    st = {}
    assert kill_scale(100.0, st) == 1.0
    assert kill_scale(89.0, st) == 0.5
    assert kill_scale(84.0, st) == 0.0
    assert kill_scale(120.0, st) == 0.0 and st["killed"]


def test_symbol_mapping():
    assert to_alpaca("BRK-B") == "BRK.B" and to_alpaca("BTC-USD") == "BTC/USD"
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement `src/search/ensemble.py`**

```python
"""Risk-parity ensemble of survivors + account kill switch."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.search.engine import cap_gross


def to_alpaca(sym: str) -> str:
    return sym.replace("-USD", "/USD") if sym.endswith("-USD") else sym.replace("-", ".")


def combine(sleeve_w: dict, sleeve_r: dict, cap: float = 0.25, pos_cap: float = 0.10) -> pd.Series:
    vol = {k: r.iloc[-63:].std() * np.sqrt(252) for k, r in sleeve_r.items()}
    inv = {k: 1.0 / v for k, v in vol.items() if v and v > 0}
    if not inv:
        return pd.Series(dtype=float)
    tot = sum(inv.values())
    alloc = {k: min(cap, v / tot) for k, v in inv.items()}
    target = pd.Series(dtype=float)
    for k, a in alloc.items():
        target = target.add(sleeve_w[k].iloc[-1] * a, fill_value=0.0)
    target = target[target.abs() > 1e-6].clip(-pos_cap, pos_cap)
    return cap_gross(target.to_frame().T).iloc[0]


def kill_scale(equity: float, state: dict) -> float:
    state["peak"] = max(state.get("peak", 0.0), equity)
    dd = equity / state["peak"] - 1
    if state.get("killed") or dd <= -0.15:
        state["killed"] = True
        return 0.0
    return 0.5 if dd <= -0.10 else 1.0
```

Note: sleeve allocations are capped at 25% and are not re-normalised up, so with few survivors the account holds cash. This is intended (no leverage, conservative).

- [ ] **Step 4:** Rerun → PASS. Commit `search: ensemble combiner and kill switch`.

- [ ] **Step 5: Write `scripts/run_ensemble.py`**

```python
"""Trade the frozen survivor ensemble on the Alpaca PAPER account.

    PYTHONPATH=. python scripts/run_ensemble.py            # dry run
    PYTHONPATH=. python scripts/run_ensemble.py --execute
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from src.broker import AlpacaPaperBroker
from src.config import load_broker_config
from src.search.engine import cap_gross, cost_table, run_weights
from src.search.ensemble import combine, kill_scale, to_alpaca
from src.search.families import S2, Ctx, Trial
from src.search.universe import CRYPTO, ETFS, load_panel, sp500_membership, top_liquid

CFG = Path("portfolio/ensemble.json")
STATE = Path("portfolio/ensemble_state.json")
LOG = Path("portfolio/ensemble_trades.csv")
MIN_ORDER = 50.0


def owned_symbols() -> set[str]:
    """Alpaca symbols the ensemble may trade (read by run_session to avoid overlap)."""
    if not CFG.exists():
        return set()
    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    return set(st.get("owned", []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    cfg = json.loads(CFG.read_text())
    trials = [Trial(t["name"], t["family"], t["params"]) for t in cfg["trials"]]
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    broker = AlpacaPaperBroker(load_broker_config())
    acct = broker.get_account()
    scale = kill_scale(acct.equity, state)

    members = sp500_membership()
    close, vol = load_panel(sorted(set(members.columns) | set(ETFS) | set(CRYPTO) | set(S2)))
    today = datetime.now(UTC).date()
    close = close[close.index.date < today]          # completed bars only
    liquid = top_liquid(close, vol.reindex_like(close),
                        members.reindex(close.index).ffill().fillna(False), n=150)
    ctx = Ctx(close=close, members=members, liquid=liquid)
    bps = cost_table(close.columns)
    sw, sr = {}, {}
    for t in trials:
        w = cap_gross(t.weights(ctx).fillna(0.0))
        sw[t.name] = w
        sr[t.name] = run_weights(w, close[w.columns], bps=bps[w.columns])
    target = combine(sw, sr) * scale if trials else None
    target = {} if target is None else {to_alpaca(k): float(v) for k, v in target.items()}

    positions = {p.symbol: p for p in broker.get_positions().values()}
    owned = set(state.get("owned", [])) | set(target)
    prices = broker.get_last_prices(sorted(s for s in owned if "/" not in s))
    market_open = broker.is_market_open()
    orders = []
    for sym in sorted(owned):
        px = prices.get(sym) or (positions[sym.replace("/", "")].current_price
                                 if sym.replace("/", "") in positions else None)
        if not px:
            continue
        held = positions.get(sym.replace("/", ""))
        held_val = held.market_value if held else 0.0
        delta = target.get(sym, 0.0) * acct.equity - held_val
        if abs(delta) < MIN_ORDER:
            continue
        side = "buy" if delta > 0 else "sell"
        qty = round(abs(delta) / px, 6) if "/" in sym else int(abs(delta) / px)
        if qty > 0:
            orders.append((0 if side == "sell" else 1, sym, side, qty, px))
    print(f"equity {acct.equity:,.2f} scale {scale} targets {len(target)} orders {len(orders)}")
    ts = datetime.now(UTC).isoformat()
    for _, sym, side, qty, px in sorted(orders):      # sells first
        is_crypto = "/" in sym
        if not is_crypto and not market_open:
            print("market closed, skip", sym)
            continue
        oid = ""
        if args.execute:
            res = broker.submit_order(sym, qty, side,
                                      time_in_force="gtc" if is_crypto else "day",
                                      client_order_id=f"ens:{today}:{sym.replace('/', '')}:{side}")
            oid = res.order_id
        print(side, qty, sym, f"~{px:.2f}", oid)
        if args.execute:
            new = not LOG.exists()
            with LOG.open("a", newline="") as fh:
                wr = csv.writer(fh)
                if new:
                    wr.writerow(["ts", "symbol", "side", "qty", "ref_price", "order_id"])
                wr.writerow([ts, sym, side, qty, px, oid])
    if args.execute:
        state["owned"] = sorted(s for s in owned if abs(target.get(s, 0.0)) > 0
                                or s.replace("/", "") in positions)
        STATE.write_text(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6:** If `retire` includes `H1`, it stays disabled (task `PaperTradingDailyRun`); if H1 survives, it trades inside the ensemble, so the old task stays disabled either way. Dry run: `PYTHONPATH=. python scripts/run_ensemble.py` → prints the planned orders, submits nothing. Check that the gross of the targets is ≤ 1 and no single position is > 10%.
- [ ] **Step 7:** Commit `search: live ensemble runner (paper)`.

---

### Task 6: Wire into sessions (no overlap, retire failed sleeves)

**Files:** Modify `src/intraday/session.py` (add `exclude` param), `scripts/run_session.py`, `scripts/run_session_local.ps1`; Test: `tests/intraday/test_session.py`

- [ ] **Step 1: Failing test** (append to `tests/intraday/test_session.py`, reusing its `_run`/`_spec`/`UP` helpers; read the file first to match their signatures)

```python
def test_excluded_symbols_are_not_traded(tmp_path):
    b = FakeBroker()            # same fake used by the other tests in this file
    rows = _run(tmp_path, b, {"A": UP}, _spec(), exclude={"A"})
    assert not [r for r in rows if r["symbol"] == "A" and r["side"] in ("buy", "sell")]
```

If `_run` doesn't forward kwargs, extend it to pass `**kw` to `run_session`.

- [ ] **Step 2:** Run → FAIL (unexpected kwarg).
- [ ] **Step 3: Implement**
  - In `run_session(...)` signature add `exclude: frozenset[str] | set[str] = frozenset(),`.
  - First line of the `for sym, w in weights.items():` loop: `if _norm(sym) in {_norm(e) for e in exclude}: continue`.
  - In `scripts/run_session.py` after `cfg = ...`:

```python
    import dataclasses, json
    from scripts.run_ensemble import owned_symbols  # noqa: E402
    ens = Path("portfolio/ensemble.json")
    retire = set(json.loads(ens.read_text()).get("retire", [])) if ens.exists() else set()
    registry = {k: (dataclasses.replace(v, active=False) if k in retire else v)
                for k, v in REGISTRY.items()}
```

  Then use `registry` instead of `REGISTRY` for `symbols` and the `run_session` call. Replace the early exit with `if not symbols and args.no_options:`. Load closes with `load_daily_closes(sorted(set(symbols) | {"SPY", "QQQ"}))` (O1/O2 underlyings). Pass `exclude=owned_symbols()`.
  - Make `scripts/` importable: create an empty `scripts/__init__.py` if one is missing.
  - In `scripts/run_session_local.ps1`, before the `run_session.py` line, add:

```powershell
$h = (Get-Date).ToUniversalTime().AddHours(-5).Hour  # approx ET; open session window only
if ($h -eq 9) { cmd /c "`"$py`" scripts/run_ensemble.py --execute >> $log 2>&1" }
```

  and add `portfolio/ensemble_state.json portfolio/ensemble_trades.csv` to its `git add` line.
- [ ] **Step 4:** `PYTHONPATH=. python -m pytest tests -q` → all pass. `python scripts/run_session.py --session open` (dry run) runs without error.
- [ ] **Step 5:** Commit `sessions: exclude ensemble symbols, retire failed sleeves`, then push.

---

## Self-review notes
- Spec coverage. Phase 1 covers: universe/survivorship (T1), costs/borrow/leverage (T2), families incl. stat-arb, regime, seasonality, crypto (T3), selection/DSR/perturbation/holdout/ledger/report (T4), ensemble, caps and kill switch (T5), existing sleeves compete/retire and no overlap (T4 `LIVE_MAP`, T6).
- Deferred to Phase 2 by design: 30-min intraday, options proxies, dashboard, weekly email.
- Names are consistent across tasks: `Ctx`, `Trial`, `grid`, `run_weights`, `cap_gross`, `cost_table`, `split_stats`, `add_dsr`, `perturb`, `dedup`, `combine`, `kill_scale`, `to_alpaca`, `owned_symbols`.
