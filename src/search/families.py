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
