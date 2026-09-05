"""Pre-trade risk engine.

Every target weight vector passes through :func:`check_and_adjust` before any
order is generated. The engine can **reduce** exposure but never increase it,
so a bug here fails toward doing less rather than more.

What a risk limit in code actually is
-------------------------------------
These limits constrain *target weights at the moment of rebalancing*. They do
not constrain what the market does between rebalances. A 25% position cap does
not stop a position reaching 30% through appreciation, and a 15% drawdown
trigger does not stop a 20% drawdown happening in a single gap. Anything
described here as a "limit" is a constraint on **our own actions**, which is
the only thing a risk engine can actually control.

This distinction is stated because risk systems are routinely oversold as
guarantees, and a project that claimed a "maximum drawdown limit" would be
making a claim it cannot support.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from src.config import ASSET_CLASS, RISK, RiskLimits

logger = logging.getLogger(__name__)


@dataclass
class RiskReport:
    """Result of a pre-trade risk check.

    Attributes:
        original: Weights as requested by the strategy.
        adjusted: Weights after limits were applied. Never larger in aggregate.
        breaches: Human-readable descriptions of every limit that bound.
        gross_exposure: Post-adjustment gross exposure.
        scale_applied: Multiplier applied to the whole book (1.0 = untouched).
        halted: True when no new risk may be taken at all.

    """

    original: pd.Series
    adjusted: pd.Series
    breaches: list[str] = field(default_factory=list)
    gross_exposure: float = 0.0
    scale_applied: float = 1.0
    halted: bool = False

    @property
    def ok(self) -> bool:
        """True when nothing bound and no halt is in force."""
        return not self.breaches and not self.halted

    def summary(self) -> str:
        """Multi-line summary for logs."""
        lines = [
            f"Gross exposure: {self.gross_exposure:.4f} "
            f"(scale {self.scale_applied:.4f})",
            f"Halted: {self.halted}",
            f"Breaches: {len(self.breaches)}",
        ]
        lines += [f"  - {b}" for b in self.breaches]
        return "\n".join(lines)


def current_drawdown(equity_history: pd.Series) -> float:
    """Return the current drawdown from the running peak, as a negative decimal.

    Args:
        equity_history: Portfolio equity over time, oldest first.

    Returns:
        0.0 when at a new high, otherwise a negative fraction.

    """
    if equity_history is None or len(equity_history) == 0:
        return 0.0
    peak = float(equity_history.max())
    if peak <= 0:
        return 0.0
    return float(equity_history.iloc[-1]) / peak - 1.0


def check_and_adjust(
    target_weights: pd.Series,
    equity_history: pd.Series | None = None,
    limits: RiskLimits = RISK,
    asset_class_map: dict[str, str] | None = None,
) -> RiskReport:
    """Apply pre-trade risk limits to a target weight vector.

    Limits are applied in a deliberate order, each one only ever reducing
    exposure:

    1. **Negative weights** are zeroed. The system is long-only.
    2. **Per-asset cap** — no single position above ``max_single_weight``.
    3. **Asset-class cap** — no class above ``max_asset_class_weight``, applied
       by scaling that class down proportionally rather than dropping names,
       so the strategy's relative preferences within the class survive.
    4. **Gross exposure cap** — total invested never exceeds
       ``max_gross_exposure``.
    5. **Drawdown de-risking** — exposure halved past the de-risk threshold.
    6. **Drawdown halt** — all exposure removed past the halt threshold.

    Args:
        target_weights: Requested weights, indexed by symbol.
        equity_history: Portfolio equity to date, for drawdown checks.
        limits: Limit set to enforce.
        asset_class_map: Symbol to asset-class mapping.

    Returns:
        A :class:`RiskReport`. ``adjusted`` is what should actually be traded.

    """
    asset_class_map = asset_class_map or ASSET_CLASS
    weights = target_weights.astype(float).fillna(0.0).copy()
    breaches: list[str] = []

    # 1. Long-only.
    negative = weights[weights < 0]
    if len(negative) > 0:
        breaches.append(
            f"Negative weights zeroed (long-only): {list(negative.index)}"
        )
        weights = weights.clip(lower=0.0)

    # 2. Per-asset cap.
    over_cap = weights[weights > limits.max_single_weight]
    if len(over_cap) > 0:
        breaches.append(
            f"Per-asset cap {limits.max_single_weight:.0%} bound on "
            f"{ {s: round(float(w), 4) for s, w in over_cap.items()} }"
        )
        weights = weights.clip(upper=limits.max_single_weight)

    # 3. Asset-class cap.
    classes = pd.Series(
        {s: asset_class_map.get(s, "unknown") for s in weights.index}
    )
    for class_name, exposure in weights.groupby(classes).sum().items():
        if exposure > limits.max_asset_class_weight:
            members = classes[classes == class_name].index
            scale = limits.max_asset_class_weight / exposure
            weights.loc[members] = weights.loc[members] * scale
            breaches.append(
                f"Asset-class cap bound on {class_name!r}: "
                f"{exposure:.4f} -> {limits.max_asset_class_weight:.4f}"
            )

    # 4. Gross exposure cap.
    gross = float(weights.sum())
    scale_applied = 1.0
    if gross > limits.max_gross_exposure:
        scale_applied = limits.max_gross_exposure / gross
        weights = weights * scale_applied
        breaches.append(
            f"Gross exposure cap bound: {gross:.4f} -> "
            f"{limits.max_gross_exposure:.4f}"
        )

    # 5/6. Drawdown response.
    halted = False
    drawdown = current_drawdown(equity_history) if equity_history is not None else 0.0

    if drawdown <= -limits.drawdown_halt_threshold:
        breaches.append(
            f"DRAWDOWN HALT: {drawdown:.2%} breaches "
            f"-{limits.drawdown_halt_threshold:.0%}. All exposure removed."
        )
        weights = weights * 0.0
        halted = True
        scale_applied = 0.0
    elif drawdown <= -limits.drawdown_derisk_threshold:
        breaches.append(
            f"DRAWDOWN DE-RISK: {drawdown:.2%} breaches "
            f"-{limits.drawdown_derisk_threshold:.0%}. Exposure halved."
        )
        weights = weights * 0.5
        scale_applied *= 0.5

    return RiskReport(
        original=target_weights,
        adjusted=weights,
        breaches=breaches,
        gross_exposure=float(weights.sum()),
        scale_applied=scale_applied,
        halted=halted,
    )


def exposure_report(
    positions_value: pd.Series,
    equity: float,
    asset_class_map: dict[str, str] | None = None,
) -> dict[str, float]:
    """Summarise current exposure for the daily snapshot.

    Args:
        positions_value: Market value per symbol.
        equity: Total portfolio equity.
        asset_class_map: Symbol to asset-class mapping.

    Returns:
        Gross and net exposure, cash weight, largest position, position count,
        and per-asset-class exposure keyed ``class_<name>``.

    """
    asset_class_map = asset_class_map or ASSET_CLASS
    if equity <= 0:
        return {"gross_exposure": 0.0, "net_exposure": 0.0, "cash_weight": 1.0}

    weights = positions_value / equity
    classes = pd.Series(
        {s: asset_class_map.get(s, "unknown") for s in weights.index}
    )

    report = {
        "gross_exposure": float(weights.abs().sum()),
        "net_exposure": float(weights.sum()),
        "cash_weight": float(1.0 - weights.sum()),
        "max_position_weight": float(weights.max()) if len(weights) else 0.0,
        "n_positions": int((weights.abs() > 1e-9).sum()),
    }
    if len(weights):
        for class_name, exposure in weights.groupby(classes).sum().items():
            report[f"class_{class_name}"] = float(exposure)
    return report
