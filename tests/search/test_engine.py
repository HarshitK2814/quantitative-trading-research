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
    # 10 bars so A's last price is more than 7 calendar days before the end
    idx = pd.bdate_range("2020-01-01", periods=10)
    close = pd.DataFrame({"A": [100, 100] + [np.nan] * 8,
                          "B": [10.0] * 10}, index=idx)
    w = pd.DataFrame({"A": [1.0] * 10, "B": [-1.0] * 10}, index=idx)
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
