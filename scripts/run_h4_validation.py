"""H4 vol-target (10%, 63d) on H1, TRAIN vs VALIDATION. Test period untouched.

Reports raw return/vol/drawdown (not just Sharpe): vol-targeting can raise
Sharpe purely by holding more cash, which lowers return.
Trials added: 25 signal configs x 2 (EW, VT10) on validation = 50.
"""
from __future__ import annotations

import logging
from datetime import date
from itertools import product

import numpy as np
import pandas as pd

from src.backtest import run_backtest
from src.config import SPLITS, UNIVERSE
from src.data import align_risk_free, load_prices, load_risk_free_rate
from src.metrics import bootstrap_sharpe_ci, summarise
from src.signals import apply_volatility_target, cross_sectional_momentum

logging.basicConfig(level=logging.ERROR)
pd.set_option("display.width", 200)
end = date.today()
px = load_prices(UNIVERSE, SPLITS.history_start, end)
rf_all = load_risk_free_rate(SPLITS.history_start, end)

def run(prices, rf, lb, k, vt):
    # warm-up: signal/vol need history before the window starts, so build on
    # full history up to the window end and slice returns to the window.
    w = cross_sectional_momentum(prices, lookback=lb, top_k=k)
    base = run_backtest(prices, w, cost_bps=10.0, rf_daily=rf)
    if not vt:
        return base
    return run_backtest(prices, apply_volatility_target(w, base.returns, 0.10),
                        cost_bps=10.0, rf_daily=rf)

for label, start, stop in (("TRAIN", SPLITS.train_start, SPLITS.train_end),
                           ("VALIDATION", SPLITS.validation_start, SPLITS.validation_end)):
    hist = px.loc[: str(stop)]
    rf = align_risk_free(rf_all, hist.index)
    mask = hist.index >= pd.Timestamp(start)
    print("=" * 96, f"\n{label} {start}..{stop} | 10 bps | primary spec 126/k5/skip21")
    out = {}
    for name, vt in (("H1 equal-weight", False), ("H1 + VT10", True)):
        r = run(hist, rf, 126, 5, vt).returns[mask]
        out[name] = summarise(r, rf=rf[mask], benchmark=hist["SPY"].pct_change()[mask])
        if label == "VALIDATION":
            ci = bootstrap_sharpe_ci(r, rf=rf[mask], n_resamples=5000)
            out[name]["sharpe_ci"] = f"[{ci['ci_low']:.2f},{ci['ci_high']:.2f}]"
    spy = summarise(hist["SPY"].pct_change()[mask], rf=rf[mask])
    out["SPY buy&hold"] = spy
    cols = ["ann_return", "ann_volatility", "sharpe", "max_drawdown", "calmar"]
    t = pd.DataFrame(out).T
    print(t[[*cols, *(["sharpe_ci"] if "sharpe_ci" in t else [])]].to_string())

    if label == "VALIDATION":
        gains, ew_s, vt_s = [], [], []
        for lb, k in product((21, 63, 126, 189, 252), (3, 4, 5, 6, 8)):
            a = run(hist, rf, lb, k, False).returns[mask]
            b = run(hist, rf, lb, k, True).returns[mask]
            sa = summarise(a, rf=rf[mask])["sharpe"]; sb = summarise(b, rf=rf[mask])["sharpe"]
            ew_s.append(sa); vt_s.append(sb); gains.append(sb - sa)
        print(f"\nValidation grid (25 configs): VT10 beats EW in "
              f"{np.mean(np.array(gains) > 0):.0%}; median Sharpe EW "
              f"{np.median(ew_s):.3f} vs VT10 {np.median(vt_s):.3f}; "
              f"median gain {np.median(gains):+.3f}")
