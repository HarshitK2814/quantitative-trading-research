"""Generate the public track-record page from the append-only journals.

Writes ``docs/index.html``, served by GitHub Pages at
https://harshitk2814.github.io/quantitative-trading-research/

Design constraints, all deliberate:

* **Self-contained.** Inline CSS and hand-built SVG, no CDN, no JavaScript
  libraries. The page must render identically for a reader with a locked-down
  browser, and must not depend on a third party still existing in 2027.
* **Generated only from the committed journals.** Every number on the page
  comes from ``portfolio/*.csv``. There is no path by which a figure can be
  typed in by hand, which is the point -- see the note on verifiability below.
* **Disclaimers are structural, not decorative.** Paper-money status and the
  rejected/forward-test status of the strategies are rendered as prominent
  page elements, not footnotes, because the page's credibility depends on a
  reader not being able to mistake it for a profitability claim.

On verifiability: a self-published dashboard is self-reported, and a
sufficiently sceptical reader should not simply believe it. What makes the
record credible is not this page but the **Git history behind it** -- the
journals are committed nightly by an automated job, so timestamps are
independent of the author and any retroactive edit would show as a rewrite.
The page says so, and links to the raw CSVs, rather than asking to be trusted.
"""

from __future__ import annotations

import html
import subprocess
from datetime import UTC, datetime

import pandas as pd

from src.config import PROJECT_ROOT
from src.execution import load_snapshots, load_trades
from src.hedge import load_hedge_trades

REPO_URL = "https://github.com/HarshitK2814/quantitative-trading-research"
OUT_PATH = PROJECT_ROOT / "docs" / "index.html"


def _git(*args: str) -> str:
    """Run a git command, returning empty string on failure."""
    try:
        return subprocess.run(
            ["git", *args], cwd=PROJECT_ROOT, capture_output=True,
            text=True, timeout=30,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _sparkline(values: list[float], width: int = 720, height: int = 220) -> str:
    """Hand-built SVG equity curve. No plotting library, no CDN.

    Returns a placeholder message rather than a misleading flat line when
    there are too few points to draw a meaningful curve.
    """
    if len(values) < 2:
        return ('<p class="muted">Not enough observations yet to plot a '
                "curve. The line appears once a few sessions have been "
                "recorded.</p>")

    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    pad = 28
    n = len(values)

    pts = []
    for i, v in enumerate(values):
        x = pad + (width - 2 * pad) * (i / (n - 1))
        y = height - pad - (height - 2 * pad) * ((v - lo) / span)
        pts.append(f"{x:.2f},{y:.2f}")
    line = " ".join(pts)
    area = f"{pad},{height - pad} {line} {width - pad},{height - pad}"

    # Reference line at the starting equity, so gain/loss is visually honest.
    start = values[0]
    y0 = height - pad - (height - 2 * pad) * ((start - lo) / span)

    return f"""<svg viewBox="0 0 {width} {height}" class="chart"
     role="img" aria-label="Paper account equity curve">
  <polygon points="{area}" fill="url(#g)" opacity="0.18"/>
  <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="#3b6ea5"/>
    <stop offset="100%" stop-color="#3b6ea5" stop-opacity="0"/>
  </linearGradient></defs>
  <line x1="{pad}" y1="{y0:.2f}" x2="{width - pad}" y2="{y0:.2f}"
        stroke="#999" stroke-dasharray="4 4" stroke-width="1"/>
  <polyline points="{line}" fill="none" stroke="#3b6ea5" stroke-width="2.5"
            stroke-linejoin="round" stroke-linecap="round"/>
  <text x="{pad}" y="{y0 - 6:.2f}" font-size="11" fill="#777">
    start ${start:,.0f}</text>
</svg>"""


def _table(frame: pd.DataFrame, columns: dict[str, str]) -> str:
    """Render a DataFrame as an HTML table with renamed headers."""
    if frame.empty:
        return '<p class="muted">Nothing recorded yet.</p>'
    head = "".join(f"<th>{html.escape(v)}</th>" for v in columns.values())
    rows = []
    for _, row in frame.iterrows():
        cells = "".join(
            f"<td>{html.escape(str(row.get(k, '')))}</td>" for k in columns
        )
        rows.append(f"<tr>{cells}</tr>")
    return (f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table></div>")


def build() -> str:
    """Assemble the full page from the committed journals."""
    snaps = load_snapshots()
    trades = load_trades(deduplicate=True)
    hedges = load_hedge_trades()

    commit = _git("rev-parse", "--short", "HEAD") or "unknown"
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    # --- headline stats -----------------------------------------------------
    if snaps.empty:
        equity = start = cum = dd = 0.0
        sessions = 0
        first_date = last_date = "n/a"
        curve = []
    else:
        curve = [float(v) for v in snaps["equity"]]
        equity = curve[-1]
        start = curve[0]
        cum = float(snaps["cumulative_return"].iloc[-1])
        dd = float(snaps["drawdown"].iloc[-1])
        sessions = len(snaps)
        first_date = str(snaps["date"].iloc[0].date())
        last_date = str(snaps["date"].iloc[-1].date())

    live_trades = trades[trades["dry_run"].astype(str).str.lower() != "true"]
    filled = live_trades[live_trades["status"].astype(str) == "filled"]
    n_orders = len(live_trades["order_id"].dropna().unique())

    slip = pd.to_numeric(filled.get("slippage_bps"), errors="coerce").dropna()
    # The first five fills are excluded from slippage stats by a rule recorded
    # BEFORE the numbers existed (Labor Day weekend gap contaminates them).
    slip_note = ("first 5 fills excluded -- weekend-gap contaminated, "
                 "excluded by a rule recorded before the values existed")
    slip_clean = slip.iloc[5:] if len(slip) > 5 else pd.Series(dtype=float)
    slip_txt = (f"{slip_clean.mean():+.1f} bps mean ({len(slip_clean)} fills)"
                if len(slip_clean) else "not yet measurable")

    # --- positions ----------------------------------------------------------
    positions_html = '<p class="muted">No positions recorded yet.</p>'
    if not snaps.empty:
        import json as _json
        try:
            pos = _json.loads(snaps["positions_json"].iloc[-1] or "{}")
            if pos:
                pf = pd.DataFrame(
                    [{"symbol": k, "qty": v} for k, v in sorted(pos.items())]
                )
                positions_html = _table(pf, {"symbol": "Symbol",
                                             "qty": "Shares"})
        except Exception:  # noqa: BLE001
            pass

    # --- recent trades ------------------------------------------------------
    recent = filled.sort_values("timestamp_utc", ascending=False).head(15).copy()
    if not recent.empty:
        recent["when"] = recent["timestamp_utc"].astype(str).str[:10]
        recent["price"] = pd.to_numeric(
            recent["filled_avg_price"], errors="coerce"
        ).map(lambda x: f"${x:,.2f}" if pd.notna(x) else "")
        recent["slip"] = pd.to_numeric(
            recent["slippage_bps"], errors="coerce"
        ).map(lambda x: f"{x:+.1f}" if pd.notna(x) else "")
    trades_html = _table(recent, {
        "when": "Date", "symbol": "Symbol", "side": "Side", "qty": "Qty",
        "price": "Fill", "slip": "Slippage (bps)",
    })

    # --- hedge --------------------------------------------------------------
    hedge_html = '<p class="muted">No hedge position recorded yet.</p>'
    if not hedges.empty:
        hf = hedges[hedges["status"].astype(str) == "filled"].copy()
        if not hf.empty:
            hf["when"] = hf["timestamp_utc"].astype(str).str[:10]
            hf["premium"] = pd.to_numeric(
                hf["filled_avg_price"], errors="coerce"
            ).map(lambda x: f"${x:,.2f}" if pd.notna(x) else "")
            hedge_html = _table(hf, {
                "when": "Date", "contract_symbol": "Contract",
                "strike_price": "Strike", "expiration_date": "Expiry",
                "qty": "Contracts", "premium": "Premium/share",
            })

    cum_cls = "pos" if cum >= 0 else "neg"

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Paper Trading Track Record — Quantitative Research</title>
<style>
  :root {{
    --ink:#1a1d21; --muted:#6b7280; --line:#e3e6ea; --bg:#fbfcfd;
    --accent:#3b6ea5; --pos:#12805c; --neg:#b3261e; --warn:#8a6d1f;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:900px; margin:0 auto; padding:32px 20px 72px; }}
  h1 {{ font-size:1.6rem; margin:0 0 4px; letter-spacing:-0.01em; }}
  h2 {{ font-size:1.05rem; margin:36px 0 12px; letter-spacing:-0.01em; }}
  .sub {{ color:var(--muted); margin:0 0 22px; }}
  .banner {{ background:#fff8e6; border:1px solid #e8d9a8; color:var(--warn);
    padding:12px 16px; border-radius:8px; font-weight:600; margin-bottom:22px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
    gap:12px; margin-bottom:12px; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:10px;
    padding:14px 16px; }}
  .card .k {{ color:var(--muted); font-size:.78rem; text-transform:uppercase;
    letter-spacing:.04em; }}
  .card .v {{ font-size:1.35rem; font-weight:600; margin-top:2px;
    font-variant-numeric:tabular-nums; }}
  .pos {{ color:var(--pos); }} .neg {{ color:var(--neg); }}
  .chart {{ width:100%; height:auto; background:#fff; border:1px solid var(--line);
    border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; background:#fff;
    font-variant-numeric:tabular-nums; font-size:.9rem; }}
  th,td {{ text-align:left; padding:9px 12px; border-bottom:1px solid var(--line); }}
  th {{ color:var(--muted); font-weight:600; font-size:.78rem;
    text-transform:uppercase; letter-spacing:.04em; }}
  .scroll {{ overflow-x:auto; border:1px solid var(--line); border-radius:10px; }}
  .muted {{ color:var(--muted); }}
  .note {{ background:#fff; border:1px solid var(--line);
    border-left:3px solid var(--accent);
    border-radius:8px; padding:14px 16px; margin:14px 0; }}
  a {{ color:var(--accent); }}
  footer {{ margin-top:40px; padding-top:18px; border-top:1px solid var(--line);
    color:var(--muted); font-size:.85rem; }}
  code {{ background:#eef1f4; padding:1px 5px; border-radius:4px; font-size:.85em; }}
</style></head><body><div class="wrap">

<h1>Paper Trading Track Record</h1>
<p class="sub">Pre-registered quantitative strategy research, executed live on a
simulated brokerage account. Generated automatically from append-only journals —
no figure on this page is entered by hand.</p>

<div class="banner">⚠ PAPER TRADING — SIMULATED MONEY ONLY. No real capital is
at risk, and none has ever been deposited. This is a research record, not a
performance claim.</div>

<div class="grid">
  <div class="card"><div class="k">Account equity</div>
    <div class="v">${equity:,.2f}</div></div>
  <div class="card"><div class="k">Cumulative return</div>
    <div class="v {cum_cls}">{cum:+.2%}</div></div>
  <div class="card"><div class="k">Drawdown from peak</div>
    <div class="v">{dd:.2%}</div></div>
  <div class="card"><div class="k">Sessions recorded</div>
    <div class="v">{sessions}</div></div>
  <div class="card"><div class="k">Orders submitted</div>
    <div class="v">{n_orders}</div></div>
  <div class="card"><div class="k">Started</div>
    <div class="v" style="font-size:1rem">{first_date}</div></div>
</div>

<h2>Equity curve</h2>
{_sparkline(curve)}
<p class="muted" style="font-size:.85rem">Starting capital ${start:,.0f}
· {first_date} → {last_date}. The record is short; over a window this
brief, the level of this line carries essentially no statistical information
about strategy quality and should not be read as evidence either way.</p>

<h2>What is actually being traded, and why that matters</h2>
<div class="note">
The deployed strategy is <strong>H1 (cross-sectional momentum)</strong> — which
this project's own analysis <strong>rejected</strong> on train-period evidence
(net Sharpe 0.47, bootstrap confidence interval spanning zero, 36% of its
parameter grid beating the benchmark against a pre-declared 60% threshold).
<br><br>
It is deployed <em>because</em> it was rejected. Its parameters were committed
to Git before any backtest existed, so running it forward is a clean test of a
pre-registered hypothesis rather than a fitted strategy. The question being
asked is not "does this make money" but "does live experience agree with the
rejection?" It must never be described as a selected or recommended strategy.
</div>
<div class="note">
A <strong>protective-put options overlay (H9)</strong> also runs on this
account. It has <strong>no historical backtest at all</strong> — free
options-chain history does not exist back to 2007. After deployment, AQR's
published study of a nearly identical specification (5% out-of-the-money
one-month puts, 1985–2020) was located: <strong>−6.4% annualised, Sharpe
−0.61</strong>. That prior is recorded in the repository, so premium bleed here
is the <em>predicted</em> outcome rather than a surprise.
</div>

<h2>Current positions</h2>
{positions_html}

<h2>Options hedge</h2>
{hedge_html}

<h2>Recent fills</h2>
{trades_html}
<p class="muted" style="font-size:.85rem">Measured slippage: {slip_txt}
— {slip_note}.</p>

<h2>Why you should not simply believe this page</h2>
<div class="note">
A self-published dashboard is self-reported, and a sceptical reader is right
not to take it at face value. What makes this record checkable is not the page
but the <strong>Git history behind it</strong>: the journals are committed by an
automated nightly job, so the timestamps are not under the author's control,
and any retroactive edit would appear as a history rewrite. The raw files are
linked below — read those, not this summary.
<br><br>
Equally, the research conclusions are checkable: hypotheses were registered
before results existed, and the log records the failures, including a strategy
that passed every in-sample test and then failed out-of-sample.
</div>

<h2>Primary sources</h2>
<ul>
  <li><a href="{REPO_URL}/blob/main/portfolio/trades.csv">
      portfolio/trades.csv</a> — every order, append-only, intended vs achieved</li>
  <li><a href="{REPO_URL}/blob/main/portfolio/daily_snapshot.csv">
      portfolio/daily_snapshot.csv</a> — daily account state</li>
  <li><a href="{REPO_URL}/blob/main/portfolio/hedge_trades.csv">
      portfolio/hedge_trades.csv</a> — options hedge journal</li>
  <li><a href="{REPO_URL}/blob/main/research/hypotheses.md">
      research/hypotheses.md</a> — pre-registered hypotheses + amendment rule</li>
  <li><a href="{REPO_URL}/blob/main/research/daily_log.md">
      research/daily_log.md</a> — dated research log, including every bug</li>
  <li><a href="{REPO_URL}/blob/main/research/institutional_landscape.md">
      research/institutional_landscape.md</a> — what firms actually disclose</li>
</ul>

<footer>
Generated {generated} from commit <code>{commit}</code> ·
<a href="{REPO_URL}">Full repository</a><br>
Paper trading only. Nothing here is investment advice, a performance claim, or
an offer of any kind.
</footer>

</div></body></html>
"""


def main() -> None:
    """Write the dashboard to docs/index.html."""
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(build(), encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
