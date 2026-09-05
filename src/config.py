"""Project configuration and the paper-trading safety interlock.

This module is deliberately the first thing any executable path imports. It
owns two responsibilities:

1.  Static research configuration (universe, date splits, cost assumptions)
    that must be identical everywhere so that no two parts of the project
    silently disagree about, say, where the out-of-sample period starts.

2.  The **paper-trading interlock**. Broker credentials are only ever handed
    out by :func:`load_broker_config`, and that function refuses to return
    anything unless the configured endpoint is the Alpaca paper endpoint and
    ``PAPER_TRADING_ONLY`` is true. There is no override flag, by design.

No secret is ever logged, printed, or included in a ``repr``. See
``BrokerConfig.__repr__``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
DATA_RAW: Final[Path] = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED: Final[Path] = PROJECT_ROOT / "data" / "processed"
FIGURES_DIR: Final[Path] = PROJECT_ROOT / "figures"
PORTFOLIO_DIR: Final[Path] = PROJECT_ROOT / "portfolio"
REPORTS_DIR: Final[Path] = PROJECT_ROOT / "reports"
LOGS_DIR: Final[Path] = PROJECT_ROOT / "logs"

for _d in (DATA_RAW, DATA_PROCESSED, FIGURES_DIR, PORTFOLIO_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Safety interlock
# ---------------------------------------------------------------------------

#: Hard-coded project invariant. This project never trades real money.
PAPER_TRADING_ONLY: Final[bool] = True

#: The only broker endpoint this project is permitted to talk to.
ALPACA_PAPER_ENDPOINT: Final[str] = "https://paper-api.alpaca.markets"

#: Endpoints that must trigger an immediate hard failure if configured.
_KNOWN_LIVE_ENDPOINTS: Final[frozenset[str]] = frozenset(
    {
        "https://api.alpaca.markets",
        "http://api.alpaca.markets",
    }
)


class LiveTradingBlockedError(RuntimeError):
    """Raised when configuration would permit anything other than paper trading.

    This is a hard failure with no override. If you are reading this because
    the exception fired, the correct response is to fix the configuration, not
    to bypass the check.
    """


# ---------------------------------------------------------------------------
# Research configuration
# ---------------------------------------------------------------------------

#: Fixed ex-ante universe. Declared in PROJECT_PLAN.md section 4 before any
#: backtest was run. Do not reorder or amend on the basis of a result; log any
#: change in research/daily_log.md with a dated reason.
UNIVERSE: Final[tuple[str, ...]] = (
    # Broad equity
    "SPY", "QQQ", "IWM", "DIA",
    # US sectors
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU",
    # Real assets
    "VNQ", "GLD", "SLV",
    # Bonds
    "TLT",
)

#: Coarse asset-class map, used by the risk engine for concentration limits.
ASSET_CLASS: Final[dict[str, str]] = {
    "SPY": "equity_broad", "QQQ": "equity_broad",
    "IWM": "equity_broad", "DIA": "equity_broad",
    "XLK": "equity_sector", "XLF": "equity_sector", "XLE": "equity_sector",
    "XLV": "equity_sector", "XLI": "equity_sector", "XLP": "equity_sector",
    "XLY": "equity_sector", "XLU": "equity_sector",
    "VNQ": "real_estate",
    "GLD": "commodity", "SLV": "commodity",
    "TLT": "bond",
}

#: Benchmark tickers pulled alongside the universe.
BENCHMARKS: Final[tuple[str, ...]] = ("SPY", "TLT")


@dataclass(frozen=True)
class DateSplits:
    """Chronological train/validation/test boundaries.

    Fixed in PROJECT_PLAN.md section 5 before any strategy was run. The test
    period is subject to the one-touch rule: it is not evaluated until the
    strategy is frozen and committed.
    """

    history_start: date = date(2007, 1, 1)
    train_start: date = date(2007, 1, 1)
    train_end: date = date(2016, 12, 31)
    validation_start: date = date(2017, 1, 1)
    validation_end: date = date(2020, 12, 31)
    test_start: date = date(2021, 1, 1)
    test_end: date = date(2025, 12, 31)

    def as_dict(self) -> dict[str, str]:
        """Return ISO-formatted boundaries, for embedding in result metadata."""
        return {
            "train": f"{self.train_start} to {self.train_end}",
            "validation": f"{self.validation_start} to {self.validation_end}",
            "test": f"{self.test_start} to {self.test_end}",
        }


SPLITS: Final[DateSplits] = DateSplits()


@dataclass(frozen=True)
class CostModel:
    """Transaction-cost assumptions.

    Costs are charged per unit of turnover, where turnover is the sum of
    absolute weight changes at a rebalance. See research/transaction_cost_model.md
    for the derivation and for why 10bps is the headline case.
    """

    #: Headline cost in basis points per unit turnover.
    headline_bps: float = 10.0
    #: Full sweep reported alongside every result. 0bps is diagnostic only.
    sweep_bps: tuple[float, ...] = (0.0, 5.0, 10.0, 20.0)

    def cost_fraction(self, bps: float | None = None) -> float:
        """Convert basis points to a decimal fraction of traded notional."""
        return (self.headline_bps if bps is None else bps) / 10_000.0


COSTS: Final[CostModel] = CostModel()


@dataclass(frozen=True)
class RiskLimits:
    """Portfolio risk limits. Rationale documented in docs/risk_management.md.

    These are research parameters chosen before results were seen. They are not
    guarantees: a limit expressed in code constrains target weights, it does not
    constrain what the market does between rebalances.
    """

    target_annual_vol: float = 0.10
    max_single_weight: float = 0.25
    max_asset_class_weight: float = 0.50
    max_gross_exposure: float = 1.00  # long-only, no leverage
    drawdown_derisk_threshold: float = 0.15
    drawdown_halt_threshold: float = 0.25
    min_trade_notional_usd: float = 50.0  # suppress dust trades


RISK: Final[RiskLimits] = RiskLimits()


#: Trading days per year, used for all annualisation. Stated explicitly because
#: an unstated annualisation convention makes a Sharpe ratio unfalsifiable.
TRADING_DAYS_PER_YEAR: Final[int] = 252

#: Random seed for every stochastic procedure (bootstrap, ML splits).
RANDOM_SEED: Final[int] = 20260905


# ---------------------------------------------------------------------------
# Broker configuration (paper only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BrokerConfig:
    """Validated Alpaca **paper** credentials.

    Instances can only be produced by :func:`load_broker_config`, which
    enforces the paper-only interlock.
    """

    api_key_id: str = field(repr=False)
    api_secret_key: str = field(repr=False)
    base_url: str

    def __repr__(self) -> str:  # pragma: no cover - trivial
        """Redact credentials so they cannot leak into logs or tracebacks."""
        return f"BrokerConfig(base_url={self.base_url!r}, credentials=<redacted>)"

    __str__ = __repr__


def assert_paper_only(base_url: str, paper_flag: str | None) -> None:
    """Raise :class:`LiveTradingBlockedError` unless this is a paper setup.

    Args:
        base_url: The broker endpoint that would be used.
        paper_flag: Raw value of the ``PAPER_TRADING_ONLY`` environment
            variable, or ``None`` if unset.

    Raises:
        LiveTradingBlockedError: If live trading is not conclusively blocked.

    Note:
        The check is allow-list based, not deny-list based. An unrecognised
        endpoint fails closed. Matching only against known live URLs would let
        a typo or a new endpoint through.

    """
    if not PAPER_TRADING_ONLY:
        raise LiveTradingBlockedError(
            "PAPER_TRADING_ONLY is False. This project does not support live "
            "trading. Refusing to construct broker credentials."
        )

    normalised = (base_url or "").strip().rstrip("/")

    if normalised in _KNOWN_LIVE_ENDPOINTS:
        raise LiveTradingBlockedError(
            f"Refusing to start: {normalised!r} is an Alpaca LIVE trading "
            f"endpoint. This project is paper-only. Set ALPACA_BASE_URL to "
            f"{ALPACA_PAPER_ENDPOINT!r}."
        )

    if normalised != ALPACA_PAPER_ENDPOINT:
        raise LiveTradingBlockedError(
            f"Refusing to start: ALPACA_BASE_URL is {normalised!r}, which is "
            f"not the permitted paper endpoint {ALPACA_PAPER_ENDPOINT!r}. "
            f"Unrecognised endpoints fail closed by design."
        )

    if (paper_flag or "").strip().lower() != "true":
        raise LiveTradingBlockedError(
            "Refusing to start: PAPER_TRADING_ONLY must be set to 'true' in "
            f"the environment. Got {paper_flag!r}."
        )


def load_broker_config(dotenv_path: Path | None = None) -> BrokerConfig:
    """Load and validate paper-trading credentials from the environment.

    Args:
        dotenv_path: Optional explicit path to a ``.env`` file. Defaults to
            ``.env`` at the project root.

    Returns:
        A validated :class:`BrokerConfig` pointing at the paper endpoint.

    Raises:
        LiveTradingBlockedError: If the configuration is not paper-only.
        RuntimeError: If credentials are missing.

    """
    load_dotenv(dotenv_path or (PROJECT_ROOT / ".env"), override=False)

    base_url = os.environ.get("ALPACA_BASE_URL", ALPACA_PAPER_ENDPOINT)
    paper_flag = os.environ.get("PAPER_TRADING_ONLY")

    # Interlock runs BEFORE credentials are read, so a misconfigured endpoint
    # fails without ever loading a secret into memory.
    assert_paper_only(base_url, paper_flag)

    key_id = os.environ.get("ALPACA_API_KEY_ID", "").strip()
    secret = os.environ.get("ALPACA_API_SECRET_KEY", "").strip()

    if not key_id or not secret:
        raise RuntimeError(
            "Alpaca paper credentials missing. Copy .env.example to .env and "
            "fill in ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY with keys "
            "generated from the *Paper Trading* section of the Alpaca "
            "dashboard. Never commit .env."
        )

    return BrokerConfig(
        api_key_id=key_id,
        api_secret_key=secret,
        base_url=base_url.strip().rstrip("/"),
    )
