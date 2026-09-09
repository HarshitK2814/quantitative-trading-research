"""Multi-strategy sleeve combiner for live deployment.

A "sleeve" is one pre-registered strategy running against a fixed fraction
of account capital. There is only one physical Alpaca paper account, so
sleeves are not separate brokerage sub-accounts -- each sleeve's own target
weights are scaled by its capital fraction and summed across sleeves, symbol
by symbol, to produce the single combined weight vector that is actually
sent through the risk engine and to the broker. "Capital fraction" is
notional bookkeeping on top of one real account, not a separate pool of
money.

Deployment discipline
----------------------
Adding a sleeve here is a live-capital decision with the same bar H1's
deployment had: the strategy must already be pre-registered in
``research/hypotheses.md`` and backtested before it is switched on. Building
this module does not, by itself, deploy anything -- the registry that uses
it (see ``scripts/run_live.py``) starts with only the already-deployed H1
sleeve active, so live behaviour is unchanged until a second sleeve is
deliberately turned on and that decision is logged in
``research/daily_log.md``, the same way H1's deployment was.

What this deliberately does NOT do: swap a sleeve out because it looks like
it is underperforming. A sleeve's ``active`` flag is flipped only by a dated,
logged decision -- never as an automatic reaction to short-term losses. Doing
otherwise would be p-hacking a live account, which is exactly what this
project's pre-registration discipline (see ``research/hypotheses.md``) exists
to prevent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Sleeve:
    """One pre-registered strategy running against a fixed capital fraction.

    Attributes:
        name: Journal label for this sleeve (used in ``strategy_version``).
        hypothesis_id: The id in ``research/hypotheses.md`` (e.g. ``"H1"``).
            Must refer to a hypothesis that already exists there -- a sleeve
            with no corresponding pre-registered hypothesis is a violation of
            this project's own rules, not a shortcut.
        capital_fraction: Fraction of total account equity notionally
            allocated to this sleeve. Fractions of all *active* sleeves must
            sum to at most 1.0; see :func:`validate_allocation`.
        signal_fn: ``prices -> weights_over_time``. Must already apply its
            own one-bar signal lag internally (every function in
            ``src/signals.py`` does).
        allow_short: Whether this sleeve is permitted to hand back negative
            weights. ``False`` for every sleeve today -- the risk engine
            still hard-enforces long-only regardless of this flag; it exists
            so that turning a short-capable sleeve on is a one-line, visible
            change rather than a silent one, once the risk engine is
            extended to actually permit it (not done yet -- see
            ``research/hypotheses.md`` H6).
        active: Whether this sleeve currently contributes to live orders.
        note: Free-text context (deployment date, rationale).

    """

    name: str
    hypothesis_id: str
    capital_fraction: float
    signal_fn: Callable[[pd.DataFrame], pd.DataFrame]
    allow_short: bool = False
    active: bool = True
    note: str = ""


def validate_allocation(sleeves: list[Sleeve]) -> None:
    """Raise if active sleeves' capital fractions overcommit the account.

    Args:
        sleeves: The full sleeve registry (active and inactive).

    Raises:
        ValueError: If active sleeves' fractions sum to more than 1.0, or if
            any short-capable sleeve is active (not yet supported -- the risk
            engine does not permit short exposure regardless of this flag).

    """
    active = [s for s in sleeves if s.active]
    total = sum(s.capital_fraction for s in active)
    if total > 1.0 + 1e-9:
        raise ValueError(
            f"Active sleeve capital fractions sum to {total:.4f} > 1.0; "
            f"reduce an allocation before running."
        )
    shorting = [s.name for s in active if s.allow_short]
    if shorting:
        raise ValueError(
            f"Sleeve(s) {shorting} are marked allow_short=True but the risk "
            f"engine does not yet permit short exposure (see H6 in "
            f"research/hypotheses.md). Refusing to run until that is built "
            f"and deliberately enabled."
        )


def combined_target_weights(
    sleeves: list[Sleeve], prices: pd.DataFrame
) -> tuple[pd.Series, dict[str, pd.Series]]:
    """Blend each active sleeve's own weights into one account-level vector.

    Each sleeve computes its full weight history from the same price panel,
    and only the latest available row is used -- consistent with how the
    single-strategy version of this ran before sleeves existed.

    Args:
        sleeves: The sleeve registry. Inactive sleeves are skipped entirely.
        prices: Price panel shared by every sleeve (each sleeve may use only
            part of it internally).

    Returns:
        A tuple of:

        * The combined weight vector, indexed by symbol, as a fraction of
          **total account equity** (not of any one sleeve's allocation).
        * A dict mapping each active sleeve's name to its own unscaled
          weight vector, for per-sleeve attribution and logging.

    """
    combined = pd.Series(dtype=float)
    per_sleeve: dict[str, pd.Series] = {}

    for sleeve in sleeves:
        if not sleeve.active:
            continue

        weights_over_time = sleeve.signal_fn(prices)
        valid = weights_over_time.dropna(how="all")
        if valid.empty:
            continue
        latest = valid.index.max()

        sleeve_weights = weights_over_time.loc[latest].fillna(0.0)
        per_sleeve[sleeve.name] = sleeve_weights

        scaled = sleeve_weights * sleeve.capital_fraction
        combined = combined.add(scaled, fill_value=0.0)

    return combined, per_sleeve
