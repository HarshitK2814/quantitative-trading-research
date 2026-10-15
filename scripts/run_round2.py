"""H11-H15 on TRAIN and VALIDATION only (pre-registered in hypotheses.md).

The test window is never loaded: prices end at SPLITS.validation_end.
Decision rules are applied literally as pre-registered. Writes
research/round2_results.md.
Trials: H11 15, H12 50, H13 12, H14 27, H15 9 = 113.
"""
from __future__ import annotations

import logging
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtest import run_backtest
from src.config import SPLITS, UNIVERSE
from src.construction import apply_risk_construction
from src.data import align_risk_free, load_prices, load_risk_free_rate
from src.metrics import annualised_return, summarise
from src.round2 import (
    apply_absolute_gate,
    apply_no_trade_band,
    apply_regime_scaling,
    common_start,
    regime_state,
)
from src.signals import apply_volatility_target, cross_sectional_momentum

logging.basicConfig(level=logging.ERROR)
OUT = Path("research/round2_results.md")
lines: list[str] = []


def say(text: str = "") -> None:
    print(text)
    lines.append(text)


px = load_prices(UNIVERSE, SPLITS.history_start, SPLITS.validation_end)
assert px.index.max() <= pd.Timestamp(SPLITS.validation_end), "test data loaded"
rf_all = load_risk_free_rate(SPLITS.history_start, SPLITS.validation_end)
rf = align_risk_free(rf_all, px.index)
spy = px["SPY"]
WINDOWS = {
    "train": (SPLITS.train_start, SPLITS.train_end),
    "validation": (SPLITS.validation_start, SPLITS.validation_end),
}


def h1(lb: int = 126, k: int = 5):
    return cross_sectional_momentum(px, lookback=lb, skip=21, top_k=k)


def stats(weights: pd.DataFrame, start: pd.Timestamp, window: str,
          cost: float = 10.0) -> dict:
    lo, hi = WINDOWS[window]
    res = run_backtest(px, weights, cost_bps=cost, rf_daily=rf)
    m = (px.index >= max(pd.Timestamp(lo), start)) & (px.index <= pd.Timestamp(hi))
    r = res.returns[m]
    t = res.turnover[(res.turnover.index >= r.index[0])
                     & (res.turnover.index <= r.index[-1])]
    s = summarise(r, rf=rf[m], turnover=t)
    return {"sharpe": s["sharpe"], "ret": s["ann_return"], "vol": s["ann_volatility"],
            "mdd": s["max_drawdown"], "turn": s["ann_turnover"]}


def table(rows: dict[str, dict]) -> None:
    df = pd.DataFrame(rows).T[["sharpe", "ret", "vol", "mdd", "turn"]]
    say("```\n" + df.round(3).to_string() + "\n```")


base_w = h1()
verdict: dict[str, str] = {}
improve: dict[str, float] = {}

# ------------------------------------------------------------------ H11
say("# Round 2 results (train + validation only; test untouched)\n")
say("## H11 no-trade band (15 configs)")
g11 = list(product((0.0, 0.02, 0.04, 0.06, 0.10), (0.5, 0.75, 1.0)))
w11 = {c: apply_no_trade_band(base_w, px, rf, *c) for c in g11}
s11 = common_start([base_w, *w11.values()])
say(f"Common evaluation start: {s11.date()}")
ok11 = True
for win in WINDOWS:
    b = stats(base_w, s11, win)
    res = {c: stats(w, s11, win) for c, w in w11.items()}
    prim = res[(0.04, 1.0)]
    rest = [v for c, v in res.items() if c != (0.0, 1.0)]
    frac = np.mean([v["sharpe"] >= b["sharpe"] for v in rest])
    c1 = prim["sharpe"] >= b["sharpe"]
    c2 = prim["turn"] <= 0.75 * b["turn"]
    c3 = frac >= 0.6
    say(f"\n{win}: baseline vs primary (b=0.04, phi=1.0)")
    table({"baseline": b, "primary": prim})
    say(f"Sharpe>=base {c1}; turnover<=75% {c2} "
        f"({prim['turn'] / b['turn']:.0%}); grid share >= base {frac:.0%} "
        f"(need 60%): {c3}")
    ok11 &= bool(c1 and c2 and c3)
    if win == "validation":
        improve["H11"] = prim["sharpe"] - b["sharpe"]
verdict["H11"] = "SUPPORTED" if ok11 else "NOT SUPPORTED"

# ------------------------------------------------------------------ H13
say("\n## H13 regime scaling (12 configs)")
g13 = list(product((0.15, 0.20, 0.25), (0.25, 0.5), (126, 252)))
w13 = {c: apply_regime_scaling(base_w, spy, c[0], c[1], c[2]) for c in g13}
s13 = common_start([base_w, *w13.values()])
say(f"Common evaluation start: {s13.date()}")
ok13, informative = True, True
for win in WINDOWS:
    lo, hi = WINDOWS[win]
    b = stats(base_w, s13, win)
    res = {c: stats(w, s13, win) for c, w in w13.items()}
    prim_key = (0.20, 0.5, 252)
    prim = res[prim_key]
    st = regime_state(spy, 0.20, 252)
    dm = (st.index >= max(pd.Timestamp(lo), s13)) & (st.index <= pd.Timestamp(hi))
    on_share = float(st[dm].fillna(0.0).mean())
    both = np.mean([v["sharpe"] >= b["sharpe"] and v["mdd"] >= b["mdd"]
                    for v in res.values()])
    c1 = prim["sharpe"] >= b["sharpe"] and prim["mdd"] >= b["mdd"]
    say(f"\n{win}: baseline vs primary (theta=.20, s=.5, W=252)")
    table({"baseline": b, "primary": prim})
    say(f"State ON {on_share:.1%} of days (need >=3%); primary meets both "
        f"{c1}; grid meeting both {both:.0%} (need 60%)")
    informative &= on_share >= 0.03
    ok13 &= bool(c1 and both >= 0.6)
    if win == "validation":
        improve["H13"] = prim["sharpe"] - b["sharpe"]
verdict["H13"] = ("UNINFORMATIVE" if not informative
                  else "SUPPORTED" if ok13 else "NOT SUPPORTED")

# ------------------------------------------------------------------ H15
say("\n## H15 absolute-momentum gate (9 configs)")
g15 = list(product((126, 189, 252), (3, 5, 8)))
w15 = {c: apply_absolute_gate(h1(126, c[1]), px, rf, c[0]) for c in g15}
s15 = common_start([base_w, *w15.values()])
say(f"Common evaluation start: {s15.date()}")
ok15 = True
for win in WINDOWS:
    b = stats(base_w, s15, win)
    res = {c: stats(w, s15, win) for c, w in w15.items()}
    prim = res[(252, 5)]
    c1 = prim["sharpe"] >= b["sharpe"] and prim["mdd"] > b["mdd"]
    n_ok = sum(v["sharpe"] >= b["sharpe"] and v["mdd"] > b["mdd"]
               for v in res.values())
    say(f"\n{win}: baseline vs primary (G=252, k=5)")
    table({"baseline": b, "primary": prim})
    say(f"Primary meets alternative {c1}; grid configs meeting it {n_ok}/9 "
        f"(need >=5)")
    ok15 &= bool(c1 and n_ok >= 5)
    if win == "validation":
        improve["H15"] = prim["sharpe"] - b["sharpe"]
verdict["H15"] = "SUPPORTED" if ok15 else "NOT SUPPORTED"

# ------------------------------------------------------------------ H14
say("\n## H14 ERC / HRP (27 evaluations)")
g14 = list(product((3, 5, 8), (63, 126, 252)))
ew14 = {c: h1(c[1], c[0]) for c in g14}
rb14 = {(m, c): apply_risk_construction(ew14[c], px, m)
        for m in ("erc", "hrp") for c in g14}
s14 = common_start([*ew14.values(), *rb14.values()])
say(f"Common evaluation start: {s14.date()} (25% cap: k=3 gross is 75%)")
ok14 = {"erc": True, "hrp": True}
for win in WINDOWS:
    ew = {c: stats(w, s14, win) for c, w in ew14.items()}
    say(f"\n{win}")
    for m in ("erc", "hrp"):
        res = {c: stats(rb14[(m, c)], s14, win) for c in g14}
        wins = sum(res[c]["sharpe"] > ew[c]["sharpe"] for c in g14)
        tr = np.mean([res[c]["turn"] / ew[c]["turn"] for c in g14])
        say(f"{m}: beats EW in {wins}/9 selections (need >=6); mean turnover "
            f"ratio {tr:.2f} (need <=1.25)")
        ok14[m] &= bool(wins >= 6 and tr <= 1.25)
        if win == "validation":
            improve[f"H14-{m}"] = (res[(5, 126)]["sharpe"] - ew[(5, 126)]["sharpe"])
    if win == "validation":
        say("Primary (k=5, L=126):")
        table({"EW": ew[(5, 126)],
               "ERC": stats(rb14[("erc", (5, 126))], s14, win),
               "HRP": stats(rb14[("hrp", (5, 126))], s14, win)})
verdict["H14"] = ("SUPPORTED (" + ",".join(m for m in ok14 if ok14[m]) + ")"
                  if any(ok14.values()) else "NOT SUPPORTED")

# ------------------------------------------------------------------ H12
say("\n## H12 diagnostic: cash drag vs timing (25 configs x 2 periods)")
share_med: dict[str, float] = {}
for win in WINDOWS:
    lo, hi = WINDOWS[win]
    shares, timing = [], []
    for lb, k in product((21, 63, 126, 189, 252), (3, 4, 5, 6, 8)):
        w = cross_sectional_momentum(px, lookback=lb, top_k=k)
        ew = run_backtest(px, w, cost_bps=10.0, rf_daily=rf)
        wv = apply_volatility_target(w, ew.returns, 0.10)
        vt = run_backtest(px, wv, cost_bps=10.0, rf_daily=rf)
        m = (px.index >= pd.Timestamp(lo)) & (px.index <= pd.Timestamp(hi))
        e = float(1.0 - vt.cash_weight[m].mean())
        ce = e * ew.returns[m] + (1 - e) * rf[m]
        den = annualised_return(ew.returns[m]) - annualised_return(vt.returns[m])
        sh_vt = summarise(vt.returns[m], rf=rf[m])["sharpe"]
        sh_ce = summarise(ce, rf=rf[m])["sharpe"]
        timing.append(sh_vt - sh_ce)
        if den > 0:
            shares.append((annualised_return(ew.returns[m])
                           - annualised_return(ce)) / den)
    share_med[win] = float(np.median(shares)) if shares else float("nan")
    say(f"{win}: configs with positive shortfall {len(shares)}/25; median "
        f"cash-drag share {share_med[win]:.2f}; median timing value "
        f"{np.median(timing):+.3f}")
verdict["H12"] = ("ACCEPTED (cash drag > 50%)" if share_med["validation"] > 0.5
                  else "REJECTED (timing, not exposure level)")

# ------------------------------------------------------------------ costs
say("\n## Cost sweep, primaries (validation)")
sweep = {}
for cost in (5.0, 10.0, 20.0):
    sweep[f"{cost:g}bps"] = {
        "base": stats(base_w, s11, "validation", cost)["sharpe"],
        "H11": stats(w11[(0.04, 1.0)], s11, "validation", cost)["sharpe"],
        "H13": stats(w13[(0.20, 0.5, 252)], s13, "validation", cost)["sharpe"],
        "H15": stats(w15[(252, 5)], s15, "validation", cost)["sharpe"],
        "H14-ERC": stats(rb14[("erc", (5, 126))], s14, "validation", cost)["sharpe"],
    }
say("```\n" + pd.DataFrame(sweep).T.round(3).to_string() + "\n```")

# ------------------------------------------------------------------ verdicts
say("\n## Verdicts (pre-registered rules, applied literally)")
for h, v in verdict.items():
    say(f"- {h}: {v}")
say("\nTrials this round: 113 (cumulative ledger >= 438).")
cands = {h: improve[h] for h in ("H11", "H13", "H15")
         if verdict[h] == "SUPPORTED"}
if verdict["H14"].startswith("SUPPORTED"):
    for m in ("erc", "hrp"):
        if ok14[m]:
            cands[f"H14-{m}"] = improve[f"H14-{m}"]
if cands:
    best = max(cands, key=cands.get)
    say(f"FREEZE CANDIDATE: {best} (validation Sharpe gain {cands[best]:+.3f}). "
        "Still requires DSR >= 0.95 for deployment eligibility.")
else:
    say("NO CANDIDATE FROZEN; test window untouched.")
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
