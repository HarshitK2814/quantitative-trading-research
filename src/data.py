"""Data acquisition, caching, and validation.

Design principles
-----------------
1.  **Reproducibility.** Every download is cached to Parquet with a manifest
    recording the vendor, the query, and the retrieval timestamp. A reviewer
    re-running the project gets the same panel, and a panel that changed
    underneath us is detectable rather than silent.

2.  **Vendor cross-checking.** Free market data is not authoritative. The same
    ETF can differ between vendors through adjustment methodology, stale
    prints, or outright errors. :func:`compare_vendors` quantifies the
    disagreement instead of assuming it away.

3.  **Fail loudly.** Validation raises on structural problems (non-monotonic
    index, duplicated dates, non-positive prices) and reports soft problems
    (gaps, outliers) rather than silently forward-filling them into a backtest.

Nothing in this module shifts or lags data. Look-ahead protection lives in
``features.py`` so that it happens in exactly one place and can be tested
there.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
import requests

from src.config import DATA_RAW, TRADING_DAYS_PER_YEAR, UNIVERSE

logger = logging.getLogger(__name__)

Vendor = Literal["yfinance", "stooq", "alpaca"]

_STOOQ_CSV_URL = "https://stooq.com/q/d/l/"
_ALPACA_DATA_URL = "https://data.alpaca.markets/v2/stocks/bars"
_REQUEST_TIMEOUT_SECONDS = 30


# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------


@dataclass
class ValidationReport:
    """Outcome of validating a price panel.

    Attributes:
        n_rows: Number of dates in the panel.
        n_cols: Number of tickers.
        first_date: Earliest date present.
        last_date: Latest date present.
        first_valid: Per-ticker first date with a non-null price.
        missing_counts: Per-ticker count of null prices after the first valid
            observation. Nulls *before* first listing are expected, not missing.
        extreme_moves: Daily returns whose absolute value exceeds the outlier
            threshold, as (date, ticker, return) triples.
        calendar_gaps: Consecutive dates separated by more than ``max_gap_days``.
        errors: Structural problems that make the panel unusable.

    """

    n_rows: int
    n_cols: int
    first_date: pd.Timestamp | None
    last_date: pd.Timestamp | None
    first_valid: dict[str, str]
    missing_counts: dict[str, int]
    extreme_moves: list[tuple[str, str, float]]
    calendar_gaps: list[tuple[str, str, int]]
    errors: list[str]

    @property
    def ok(self) -> bool:
        """True when no structural errors were found."""
        return not self.errors

    def summary(self) -> str:
        """Human-readable one-block summary for logs and notebooks."""
        lines = [
            f"Panel: {self.n_rows} rows x {self.n_cols} tickers "
            f"[{self.first_date} .. {self.last_date}]",
            f"Structural errors: {len(self.errors)}",
        ]
        if self.errors:
            lines += [f"  ERROR: {e}" for e in self.errors]
        gaps = [g for g in self.calendar_gaps]
        lines.append(f"Calendar gaps > threshold: {len(gaps)}")
        for a, b, n in gaps[:5]:
            lines.append(f"  gap {n}d: {a} -> {b}")
        missing = {k: v for k, v in self.missing_counts.items() if v}
        lines.append(f"Tickers with interior missing values: {len(missing)}")
        for k, v in list(missing.items())[:10]:
            lines.append(f"  {k}: {v} missing after first listing")
        lines.append(f"Extreme daily moves flagged: {len(self.extreme_moves)}")
        for d, t, r in self.extreme_moves[:5]:
            lines.append(f"  {d} {t}: {r:+.2%}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def _universe_tag(tickers: Sequence[str]) -> str:
    """Return a short, stable fingerprint of a ticker set.

    The cache key MUST include the ticker set. An earlier version keyed only on
    (vendor, start, end), so a one-ticker download silently overwrote the cache
    file holding the full 16-ticker panel -- and every later run then read a
    single-column panel back believing it was the full universe. Sorted so that
    ticker ordering does not produce spurious cache misses.
    """
    joined = ",".join(sorted(str(t) for t in tickers))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:8]


def _cache_path(vendor: str, start: date, end: date, tickers: Sequence[str]) -> Path:
    """Deterministic cache filename for a (vendor, window, universe) triple."""
    tag = _universe_tag(tickers)
    return DATA_RAW / (
        f"prices_{vendor}_{start:%Y%m%d}_{end:%Y%m%d}_{len(tickers)}x{tag}.parquet"
    )


def _manifest_path(vendor: str, start: date, end: date, tickers: Sequence[str]) -> Path:
    return _cache_path(vendor, start, end, tickers).with_suffix(".json")


def _write_manifest(
    vendor: str, start: date, end: date, tickers: Sequence[str], frame: pd.DataFrame
) -> None:
    """Record provenance beside the cached data.

    The manifest is what makes a cached file auditable: without it, a Parquet
    file on disk is data of unknown origin.
    """
    manifest = {
        "vendor": vendor,
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "requested_tickers": list(tickers),
        "universe_tag": _universe_tag(tickers),
        "returned_tickers": [str(c) for c in frame.columns],
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
        "n_rows": int(frame.shape[0]),
        "first_date": str(frame.index.min().date()) if len(frame) else None,
        "last_date": str(frame.index.max().date()) if len(frame) else None,
        "field": "adjusted_close",
    }
    _manifest_path(vendor, start, end, tickers).write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


def _download_yfinance(
    tickers: Sequence[str], start: date, end: date
) -> pd.DataFrame:
    """Download dividend- and split-adjusted closes from Yahoo Finance."""
    import yfinance as yf

    raw = yf.download(
        list(tickers),
        start=start.isoformat(),
        end=end.isoformat(),
        auto_adjust=True,  # 'Close' becomes the adjusted close
        progress=False,
        actions=False,
        threads=True,
    )
    if raw is None or raw.empty:
        raise RuntimeError("yfinance returned no data for the requested window.")

    # Column shape differs between single- and multi-ticker requests, and
    # between yfinance versions. Normalise to a plain ticker-keyed frame.
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            close = raw.xs("Close", axis=1, level=0)
        else:  # group_by='ticker' orientation
            close = raw.xs("Close", axis=1, level=-1)
    else:
        close = raw[["Close"]].rename(columns={"Close": tickers[0]})

    close = close.copy()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close.index.name = "date"
    return close.sort_index()


def _download_stooq_single(ticker: str, start: date, end: date) -> pd.Series:
    """Download one ticker's daily closes from Stooq's public CSV endpoint."""
    params = {
        "s": f"{ticker.lower()}.us",
        "i": "d",
        "d1": start.strftime("%Y%m%d"),
        "d2": end.strftime("%Y%m%d"),
    }
    response = requests.get(
        _STOOQ_CSV_URL, params=params, timeout=_REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    text = response.text.strip()

    # Stooq signals "no data" with a plain-text body rather than an HTTP error.
    if not text or "Date" not in text.split("\n", 1)[0]:
        raise RuntimeError(
            f"Stooq returned no usable data for {ticker!r}: {text[:120]!r}"
        )

    frame = pd.read_csv(io.StringIO(text), parse_dates=["Date"])
    series = frame.set_index("Date")["Close"].sort_index()
    series.index = pd.to_datetime(series.index).normalize()
    series.name = ticker
    return series


def _download_stooq(tickers: Sequence[str], start: date, end: date) -> pd.DataFrame:
    """Download daily closes for several tickers from Stooq.

    Warning:
        **Blocked as of 2026-09-05.** Stooq now serves a JavaScript
        proof-of-work bot challenge to non-browser clients: the CSV endpoint
        returns HTTP 200 with an HTML challenge body instead of CSV, which
        surfaces here as a parse failure or a 404 depending on the request
        headers. This is a deliberate anti-automation measure, not a transient
        outage, and it cannot be worked around without executing JavaScript —
        which would make the project depend on scraping a site that has
        explicitly declined automated access.

        Retained so the attempt is reproducible and the failure is verifiable
        by a reviewer. The cross-check role has moved to :func:`_download_alpaca`.
        See ``data/DATA_SOURCES.md`` for the full record.

    Note:
        Stooq's US ETF series were also split-adjusted but **not** consistently
        dividend-adjusted, so it was only ever suitable as a cross-check on
        price behaviour, never as a return source.

    """
    frames: list[pd.Series] = []
    failed: list[str] = []
    for ticker in tickers:
        try:
            frames.append(_download_stooq_single(ticker, start, end))
        except Exception as exc:  # noqa: BLE001 - vendor errors are expected
            logger.warning("Stooq download failed for %s: %s", ticker, exc)
            failed.append(ticker)
    if not frames:
        raise RuntimeError(f"Stooq returned nothing for all tickers: {list(tickers)}")
    if failed:
        logger.warning("Stooq cross-check missing %d tickers: %s", len(failed), failed)

    panel = pd.concat(frames, axis=1).sort_index()
    panel.index.name = "date"
    return panel


def _download_alpaca(tickers: Sequence[str], start: date, end: date) -> pd.DataFrame:
    """Download daily bars from Alpaca's market-data API (cross-check vendor).

    This is the designated independent cross-check, replacing Stooq. It is the
    strongest available choice for a specific reason: it is the **same data
    source the live paper account trades against**. Disagreement between this
    panel and the yfinance research panel is therefore not an academic
    curiosity — it is a direct, quantified estimate of the research-to-execution
    divergence that week 11's live-vs-backtest reconciliation must separate from
    genuine slippage.

    Args:
        tickers: Symbols to fetch.
        start: Inclusive start date.
        end: Exclusive end date.

    Returns:
        Date-indexed panel of adjusted daily closes.

    Raises:
        RuntimeError: If credentials are absent or the API returns no data.

    Note:
        Free/paper accounts receive **IEX-only** data (Alpaca docs, "Paper
        Trading"), which is thinner than the consolidated SIP feed and has
        shorter history. Coverage must be verified empirically for the
        requested window rather than assumed; a short overlap is still a valid
        cross-check, it is simply a cross-check over fewer days.

    """
    from src.config import load_broker_config

    # Reuses the paper-only interlock: this call fails closed if the
    # environment is not configured for paper trading.
    broker = load_broker_config()

    frames: list[pd.Series] = []
    for ticker in tickers:
        params = {
            "symbols": ticker,
            "timeframe": "1Day",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "adjustment": "all",  # split + dividend adjusted
            "limit": 10_000,
            "feed": "iex",
        }
        headers = {
            "APCA-API-KEY-ID": broker.api_key_id,
            "APCA-API-SECRET-KEY": broker.api_secret_key,
        }
        rows: list[dict] = []
        page_token: str | None = None
        while True:
            if page_token:
                params["page_token"] = page_token
            response = requests.get(
                _ALPACA_DATA_URL,
                params=params,
                headers=headers,
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            rows.extend(payload.get("bars", {}).get(ticker, []))
            page_token = payload.get("next_page_token")
            if not page_token:
                break

        if not rows:
            logger.warning("Alpaca returned no bars for %s", ticker)
            continue

        frame = pd.DataFrame(rows)
        series = pd.Series(
            frame["c"].to_numpy(),
            index=pd.to_datetime(frame["t"]).dt.tz_localize(None).dt.normalize(),
            name=ticker,
        )
        frames.append(series[~series.index.duplicated(keep="last")].sort_index())

    if not frames:
        raise RuntimeError(
            "Alpaca returned no data for any requested ticker. Check that "
            "paper credentials are set in .env and that the requested window "
            "falls within IEX history coverage."
        )

    panel = pd.concat(frames, axis=1).sort_index()
    panel.index.name = "date"
    return panel


def verify_adjustment_consistency(
    tickers: Sequence[str] = UNIVERSE,
    start: date = date(2007, 1, 1),
    end: date | None = None,
    tolerance: float = 1e-4,
) -> pd.DataFrame:
    """Check that adjusted closes are internally consistent with corporate actions.

    This is an **independent check that requires no second vendor and no API
    key**, which matters because the intended cross-check vendor (Stooq) became
    unavailable and the replacement (Alpaca) requires credentials.

    The method: request unadjusted closes plus the dividend and split history,
    reconstruct the adjustment factor from those corporate actions, apply it,
    and compare the result against the vendor's own adjusted series. It targets
    exactly the failure mode a vendor cross-check was meant to catch — a
    mis-applied split or dividend adjustment, which silently injects a large
    fake return into a backtest on the adjustment date.

    What it does **not** catch: an error present in the underlying raw prices
    themselves, or one shared by both the raw series and the actions. Those
    require a genuinely independent vendor. This check is a partial substitute,
    and is documented as such.

    Args:
        tickers: Symbols to verify.
        start: Inclusive start date.
        end: Exclusive end date. Defaults to today.
        tolerance: Absolute daily-return difference above which a day counts as
            a mismatch.

    Returns:
        Per-ticker frame with the number of compared days, mismatching days,
        the largest absolute return difference, and the date on which it
        occurred.

    """
    import yfinance as yf

    end = end or date.today()
    rows = []

    for ticker in tickers:
        handle = yf.Ticker(ticker)
        history = handle.history(
            start=start.isoformat(),
            end=end.isoformat(),
            auto_adjust=False,
            actions=True,
        )
        if history.empty:
            rows.append(
                {"ticker": ticker, "compared_days": 0, "mismatch_days": 0,
                 "max_abs_diff": np.nan, "worst_date": None}
            )
            continue

        history.index = pd.to_datetime(history.index).tz_localize(None).normalize()
        close = history["Close"].astype(float)
        dividends = history.get(
            "Dividends", pd.Series(0.0, index=history.index)
        ).fillna(0.0)

        # IMPORTANT: yfinance's `auto_adjust=False` "Close" is already
        # back-adjusted for splits; only the dividend adjustment is withheld.
        # An earlier version of this function multiplied by the split ratio
        # here and double-counted every split, producing a spurious ~100%
        # return difference on 2:1 split dates and ~900% on SLV's 10:1 split.
        # The split term is therefore deliberately absent. Do not reintroduce
        # it without re-checking the vendor's adjustment semantics first.
        prev_close = close.shift(1)
        reconstructed = (close + dividends).div(prev_close).sub(1.0)

        vendor_adjusted = load_prices(
            [ticker], start, end, vendor="yfinance", use_cache=False
        )[ticker]
        vendor_returns = vendor_adjusted.pct_change(fill_method=None)

        both = pd.concat(
            [reconstructed.rename("recon"), vendor_returns.rename("vendor")], axis=1
        ).dropna()
        if both.empty:
            rows.append(
                {"ticker": ticker, "compared_days": 0, "mismatch_days": 0,
                 "max_abs_diff": np.nan, "worst_date": None}
            )
            continue

        diff = (both["recon"] - both["vendor"]).abs()
        rows.append(
            {
                "ticker": ticker,
                "compared_days": int(len(both)),
                "mismatch_days": int((diff > tolerance).sum()),
                "max_abs_diff": float(diff.max()),
                "worst_date": str(diff.idxmax().date()),
            }
        )

    return pd.DataFrame(rows).set_index("ticker").sort_values(
        "mismatch_days", ascending=False
    )


def load_prices(
    tickers: Sequence[str] = UNIVERSE,
    start: date = date(2007, 1, 1),
    end: date | None = None,
    vendor: Vendor = "yfinance",
    use_cache: bool = True,
    refresh: bool = False,
) -> pd.DataFrame:
    """Load a daily adjusted-close panel, using the on-disk cache when possible.

    Args:
        tickers: Symbols to load.
        start: Inclusive start date.
        end: Exclusive end date. Defaults to today.
        vendor: ``"yfinance"`` (adjusted closes) or ``"stooq"`` (cross-check).
        use_cache: Read from the Parquet cache when a matching file exists.
        refresh: Force a re-download even if a cache file exists.

    Returns:
        A DataFrame indexed by date with one column per ticker. Values are
        adjusted closes for yfinance and raw closes for Stooq.

    Raises:
        RuntimeError: If the vendor returns no usable data.

    """
    end = end or date.today()
    cache = _cache_path(vendor, start, end, tickers)

    if use_cache and not refresh and cache.exists():
        logger.info("Loading cached %s panel from %s", vendor, cache.name)
        return pd.read_parquet(cache)

    logger.info(
        "Downloading %d tickers from %s [%s .. %s]", len(tickers), vendor, start, end
    )
    if vendor == "yfinance":
        panel = _download_yfinance(tickers, start, end)
    elif vendor == "stooq":
        panel = _download_stooq(tickers, start, end)
    elif vendor == "alpaca":
        panel = _download_alpaca(tickers, start, end)
    else:  # pragma: no cover - guarded by Literal
        raise ValueError(f"Unknown vendor {vendor!r}")

    # Preserve the requested ticker order for any that came back.
    present = [t for t in tickers if t in panel.columns]
    panel = panel[present]

    panel.to_parquet(cache)
    _write_manifest(vendor, start, end, tickers, panel)
    logger.info("Cached %s panel -> %s", vendor, cache.name)
    return panel


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_panel(
    panel: pd.DataFrame,
    outlier_threshold: float = 0.20,
    max_gap_days: int = 5,
) -> ValidationReport:
    """Check a price panel for structural and data-quality problems.

    Args:
        panel: Date-indexed price panel.
        outlier_threshold: Absolute daily return above which a move is flagged
            for manual inspection. Not automatically removed — a 20% ETF move
            can be real (March 2020) or a bad print, and only inspection tells
            them apart.
        max_gap_days: Calendar-day gap above which a break is reported. Normal
            weekends are 3 days; holidays extend that, so 5 is the practical
            threshold for "worth a look".

    Returns:
        A :class:`ValidationReport`. Structural problems populate ``errors``
        and set ``ok`` to False.

    """
    errors: list[str] = []

    if not isinstance(panel.index, pd.DatetimeIndex):
        errors.append("Index is not a DatetimeIndex.")
    else:
        if not panel.index.is_monotonic_increasing:
            errors.append("Index is not sorted ascending.")
        if panel.index.has_duplicates:
            dupes = panel.index[panel.index.duplicated()].unique()
            errors.append(f"Duplicated dates in index: {list(dupes)[:5]}")

    numeric = panel.select_dtypes(include=[np.number])
    if numeric.shape[1] != panel.shape[1]:
        non_numeric = set(panel.columns) - set(numeric.columns)
        errors.append(f"Non-numeric columns present: {sorted(non_numeric)}")

    if (numeric <= 0).any().any():
        bad = numeric.columns[(numeric <= 0).any()].tolist()
        errors.append(f"Non-positive prices in: {bad}")

    # Per-ticker first valid observation. Nulls before an ETF's inception are
    # expected; nulls after it are the problem.
    first_valid: dict[str, str] = {}
    missing_counts: dict[str, int] = {}
    for col in panel.columns:
        series = panel[col]
        fv = series.first_valid_index()
        first_valid[str(col)] = str(fv.date()) if fv is not None else "NEVER"
        missing_counts[str(col)] = (
            int(series.loc[fv:].isna().sum()) if fv is not None else int(len(series))
        )

    # Outliers, computed on returns after first listing.
    returns = panel.pct_change(fill_method=None)
    extreme: list[tuple[str, str, float]] = []
    stacked = returns.stack(future_stack=True).dropna()
    flagged = stacked[stacked.abs() > outlier_threshold]
    for (dt, ticker), value in flagged.items():
        extreme.append((str(pd.Timestamp(dt).date()), str(ticker), float(value)))

    # Calendar gaps.
    gaps: list[tuple[str, str, int]] = []
    if isinstance(panel.index, pd.DatetimeIndex) and len(panel.index) > 1:
        deltas = panel.index.to_series().diff().dt.days
        for dt, delta in deltas[deltas > max_gap_days].items():
            position = panel.index.get_loc(dt)
            previous = panel.index[position - 1]
            gaps.append((str(previous.date()), str(pd.Timestamp(dt).date()), int(delta)))

    return ValidationReport(
        n_rows=int(panel.shape[0]),
        n_cols=int(panel.shape[1]),
        first_date=panel.index.min() if len(panel) else None,
        last_date=panel.index.max() if len(panel) else None,
        first_valid=first_valid,
        missing_counts=missing_counts,
        extreme_moves=extreme,
        calendar_gaps=gaps,
        errors=errors,
    )


def compare_vendors(
    primary: pd.DataFrame,
    secondary: pd.DataFrame,
    tolerance: float = 0.005,
) -> pd.DataFrame:
    """Quantify disagreement between two vendors' price series.

    Comparison is on **daily returns**, not price levels, because the two
    vendors apply different dividend adjustments: Yahoo's adjusted closes are
    dividend-adjusted while Stooq's are generally not, so levels diverge by
    accumulated dividends even when both are correct. Returns still differ by
    the dividend on ex-dates, so a residual gap of roughly the annual dividend
    yield spread across a handful of ex-dates is *expected* and is not an error.

    What this test is really looking for is a **structural** break: a ticker
    where returns disagree on many days, which indicates a split-adjustment
    error, a stale series, or a symbol mismatch.

    Args:
        primary: Primary vendor panel (yfinance).
        secondary: Secondary vendor panel (Stooq).
        tolerance: Absolute daily return difference above which a day counts as
            a disagreement.

    Returns:
        Per-ticker comparison indexed by ticker, with the number of overlapping
        days, count and fraction of disagreeing days, the largest absolute
        difference, and the correlation of the two return series.

    """
    common_tickers = [c for c in primary.columns if c in secondary.columns]
    common_dates = primary.index.intersection(secondary.index)

    r_primary = primary.loc[common_dates, common_tickers].pct_change(fill_method=None)
    r_secondary = secondary.loc[common_dates, common_tickers].pct_change(fill_method=None)

    rows = []
    for ticker in common_tickers:
        a, b = r_primary[ticker], r_secondary[ticker]
        both = pd.concat([a, b], axis=1).dropna()
        if both.empty:
            rows.append(
                {
                    "ticker": ticker, "overlap_days": 0, "disagree_days": 0,
                    "disagree_frac": np.nan, "max_abs_diff": np.nan,
                    "return_corr": np.nan,
                }
            )
            continue
        diff = (both.iloc[:, 0] - both.iloc[:, 1]).abs()
        rows.append(
            {
                "ticker": ticker,
                "overlap_days": int(len(both)),
                "disagree_days": int((diff > tolerance).sum()),
                "disagree_frac": float((diff > tolerance).mean()),
                "max_abs_diff": float(diff.max()),
                "return_corr": float(both.iloc[:, 0].corr(both.iloc[:, 1])),
            }
        )
    return pd.DataFrame(rows).set_index("ticker").sort_values(
        "disagree_frac", ascending=False
    )


def to_returns(panel: pd.DataFrame) -> pd.DataFrame:
    """Convert an adjusted-price panel to simple daily returns.

    Uses ``fill_method=None`` so that a missing price produces a missing
    return rather than a silently forward-filled zero. A forward-filled zero is
    a fabricated observation, and fabricated observations flatter volatility
    estimates and inflate Sharpe ratios.
    """
    return panel.pct_change(fill_method=None)


def common_history_start(panel: pd.DataFrame) -> pd.Timestamp:
    """Return the first date on which every column has data.

    This is the earliest date a cross-sectional strategy can legitimately
    begin: ranking assets against each other requires all of them to exist.
    """
    firsts = [panel[c].first_valid_index() for c in panel.columns]
    firsts = [f for f in firsts if f is not None]
    if not firsts:
        raise ValueError("No column in the panel has any valid data.")
    return max(firsts)


def annualisation_factor() -> float:
    """Return the square-root-of-time factor used throughout the project."""
    return float(np.sqrt(TRADING_DAYS_PER_YEAR))


# ---------------------------------------------------------------------------
# Risk-free rate
# ---------------------------------------------------------------------------

_FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

#: Days to maturity assumed for the 3-month bill. FRED's DTB3 is the 13-week
#: bill, i.e. 91 days.
_BILL_DAYS_TO_MATURITY: int = 91


def discount_to_bond_equivalent(discount_rate_pct: pd.Series) -> pd.Series:
    """Convert a bank-discount quote to a bond-equivalent (investment) yield.

    FRED's ``DTB3`` is quoted **on a discount basis**, annualised over a 360-day
    year against the bill's *face value*. A simple return is earned on the
    *purchase price*, over a 365-day year. Subtracting the raw quoted number
    from a strategy's returns is therefore wrong twice over, and biases every
    Sharpe ratio in the project.

    The conversion, per 100 of face value:

    .. code-block:: text

        P    = 100 * (1 - d * n / 360)      purchase price
        HPR  = (100 - P) / P               return actually earned over n days
        BEY  = HPR * 365 / n               annualised on an investment basis

    Args:
        discount_rate_pct: Quoted discount rate in **percent** (e.g. ``3.71``),
            as published.

    Returns:
        Bond-equivalent yield as a **decimal** (e.g. ``0.0378``), indexed
        identically to the input.

    Example:
        A 5% discount quote on a 91-day bill corresponds to a ~5.13%
        bond-equivalent yield -- the textbook result, and the reason the
        distinction matters.

    """
    d = discount_rate_pct.astype(float) / 100.0
    n = _BILL_DAYS_TO_MATURITY
    price = 1.0 - d * n / 360.0
    holding_period_return = (1.0 - price) / price
    return holding_period_return * 365.0 / n


def annual_to_daily_rate(annual_rate: pd.Series) -> pd.Series:
    """Convert an annualised rate to a per-trading-day compounded rate.

    Uses geometric de-annualisation, ``(1 + r)**(1/252) - 1``, rather than the
    linear ``r / 252``. At the rates seen in this sample the two differ by only
    a few hundredths of a basis point per day, but the geometric form is the
    one consistent with compounding daily returns, and stating the convention
    is what makes a reported Sharpe ratio falsifiable.

    Args:
        annual_rate: Annualised rate as a decimal.

    Returns:
        Daily rate as a decimal.

    """
    return (1.0 + annual_rate) ** (1.0 / TRADING_DAYS_PER_YEAR) - 1.0


def load_risk_free_rate(
    start: date = date(2007, 1, 1),
    end: date | None = None,
    series_id: str = "DTB3",
    use_cache: bool = True,
    refresh: bool = False,
) -> pd.DataFrame:
    """Load the risk-free rate from FRED and convert it to a daily rate.

    Args:
        start: Inclusive start date.
        end: Inclusive end date. Defaults to today.
        series_id: FRED series. Defaults to ``DTB3`` (3-month T-bill, discount
            basis, secondary market).
        use_cache: Read the on-disk cache when present.
        refresh: Force a re-download.

    Returns:
        DataFrame indexed by date with columns:
        ``discount_pct`` (as published), ``bey_annual`` (bond-equivalent yield,
        decimal), and ``rf_daily`` (per-trading-day rate, decimal).

    Note:
        FRED marks non-observation days (market holidays) with ``"."``. These
        become NaN and are **forward-filled**, because the overnight rate does
        persist across a holiday -- unlike a missing *price*, which must never
        be filled. The distinction matters: filling a price fabricates a return,
        while filling a rate reflects that the rate genuinely did not change.

    """
    end = end or date.today()
    cache = DATA_RAW / f"riskfree_{series_id}_{start:%Y%m%d}_{end:%Y%m%d}.parquet"

    if use_cache and not refresh and cache.exists():
        logger.info("Loading cached risk-free series from %s", cache.name)
        return pd.read_parquet(cache)

    logger.info("Downloading %s from FRED [%s .. %s]", series_id, start, end)
    response = requests.get(
        _FRED_CSV_URL,
        params={"id": series_id, "cosd": start.isoformat(), "coed": end.isoformat()},
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    raw = pd.read_csv(io.StringIO(response.text))
    date_col = raw.columns[0]
    frame = pd.DataFrame(
        {"discount_pct": pd.to_numeric(raw[series_id], errors="coerce").to_numpy()},
        index=pd.to_datetime(raw[date_col]).dt.normalize(),
    )
    frame.index.name = "date"
    frame = frame.sort_index()

    if frame["discount_pct"].isna().all():
        raise RuntimeError(f"FRED returned no usable observations for {series_id!r}.")

    # Holidays only; see docstring for why filling a rate is legitimate.
    frame["discount_pct"] = frame["discount_pct"].ffill()
    frame["bey_annual"] = discount_to_bond_equivalent(frame["discount_pct"])
    frame["rf_daily"] = annual_to_daily_rate(frame["bey_annual"])

    frame.to_parquet(cache)
    logger.info("Cached risk-free series -> %s", cache.name)
    return frame


def align_risk_free(rf: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    """Align a daily risk-free series to a price panel's trading calendar.

    Args:
        rf: Output of :func:`load_risk_free_rate`.
        index: The target trading-day index.

    Returns:
        ``rf_daily`` reindexed onto ``index``, forward-filled across any FRED
        publication gaps, with a leading gap back-filled from the first
        observation.

    """
    return rf["rf_daily"].reindex(index).ffill().bfill()
