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
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
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
