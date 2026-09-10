"""Tests for H9's options hedge selection/sizing logic and journal.

All offline -- no broker connection, no network. The contract/quote
verification against the real Alpaca API happened separately (see
research/daily_log.md) and is not re-run here on every test invocation.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.broker import OptionContract, OptionQuote
from src.hedge import (
    expiry_window,
    load_hedge_trades,
    needs_roll,
    parse_occ_expiry,
    plan_hedge,
    record_hedge_trade,
    select_put_contract,
    size_hedge,
    update_hedge_fills,
)


def _contract(strike: float, expiry: date = date(2026, 10, 2)) -> OptionContract:
    return OptionContract(
        symbol=f"SPY261002P{int(strike * 1000):08d}",
        underlying_symbol="SPY",
        option_type="put",
        strike_price=strike,
        expiration_date=expiry,
        tradable=True,
    )


# ---------------------------------------------------------------------------
# select_put_contract
# ---------------------------------------------------------------------------


def test_selects_contract_nearest_5pct_otm() -> None:
    contracts = [_contract(s) for s in (700, 710, 720, 725, 730, 740)]
    chosen = select_put_contract(contracts, underlying_price=760.0)
    # target = 760 * 0.95 = 722; 720 is nearer than 725 (2 vs 3)
    assert chosen.strike_price == 720.0


def test_select_put_contract_empty_list_returns_none() -> None:
    assert select_put_contract([], underlying_price=760.0) is None


def test_select_put_contract_zero_price_returns_none() -> None:
    assert select_put_contract([_contract(700)], underlying_price=0.0) is None


# ---------------------------------------------------------------------------
# expiry_window / needs_roll
# ---------------------------------------------------------------------------


def test_expiry_window_matches_fixed_rule() -> None:
    lo, hi = expiry_window(date(2026, 9, 10))
    assert lo == date(2026, 10, 1)
    assert hi == date(2026, 10, 15)


def test_needs_roll_true_under_trigger() -> None:
    assert needs_roll(date(2026, 9, 20), as_of=date(2026, 9, 10)) is True  # 10 DTE


def test_needs_roll_false_at_or_above_trigger() -> None:
    assert needs_roll(date(2026, 9, 25), as_of=date(2026, 9, 10)) is False  # 15 DTE


# ---------------------------------------------------------------------------
# size_hedge
# ---------------------------------------------------------------------------


def test_size_hedge_rounds_down_to_whole_contracts() -> None:
    contract = _contract(700)  # notional/contract = 70,000
    qty, covered = size_hedge(gross_equity_exposure=150_000.0, contract=contract)
    assert qty == 2  # floor(150000/70000) = 2
    assert covered == pytest.approx(140_000.0)


def test_size_hedge_never_overstates_coverage() -> None:
    contract = _contract(700)
    qty, covered = size_hedge(gross_equity_exposure=69_999.0, contract=contract)
    assert qty == 0
    assert covered == 0.0


def test_size_hedge_zero_exposure() -> None:
    assert size_hedge(0.0, _contract(700)) == (0, 0.0)


# ---------------------------------------------------------------------------
# plan_hedge (selection + sizing combined)
# ---------------------------------------------------------------------------


def test_plan_hedge_end_to_end() -> None:
    contracts = [_contract(s) for s in (700, 720, 725, 730)]
    quotes = {
        "SPY261002P00720000": OptionQuote("SPY261002P00720000", bid=3.10, ask=3.20),
    }
    selection = plan_hedge(
        contracts, quotes, underlying_price=758.0, gross_equity_exposure=150_000.0
    )
    assert selection is not None
    assert selection.contract.strike_price == 720.0
    # target = 758*0.95=720.1, nearest is 720
    assert selection.contracts_to_buy == 2  # floor(150000/72000)
    assert selection.estimated_premium_per_contract == pytest.approx(315.0)  # 3.15*100
    assert selection.estimated_total_cost == pytest.approx(630.0)


def test_plan_hedge_missing_quote_defaults_cost_to_zero_not_fabricated() -> None:
    """No quote available -> cost is reported as 0, not guessed."""
    contracts = [_contract(700)]
    selection = plan_hedge(contracts, {}, underlying_price=730.0,
                           gross_equity_exposure=100_000.0)
    assert selection is not None
    assert selection.estimated_premium_per_contract == 0.0


def test_plan_hedge_returns_none_when_exposure_too_small() -> None:
    contracts = [_contract(700)]
    selection = plan_hedge(contracts, {}, underlying_price=730.0,
                           gross_equity_exposure=1_000.0)
    assert selection is None


def test_plan_hedge_returns_none_with_no_contracts() -> None:
    assert plan_hedge([], {}, underlying_price=730.0,
                      gross_equity_exposure=100_000.0) is None


# ---------------------------------------------------------------------------
# parse_occ_expiry
# ---------------------------------------------------------------------------


def test_parse_occ_expiry_standard_symbol() -> None:
    assert parse_occ_expiry("SPY261002P00725000") == date(2026, 10, 2)


def test_parse_occ_expiry_works_regardless_of_root_length() -> None:
    # 1-char and 4-char roots both keep the same 15-char fixed suffix.
    assert parse_occ_expiry("F261002P00012000") == date(2026, 10, 2)
    assert parse_occ_expiry("GOOGL261002P00150000") == date(2026, 10, 2)


def test_parse_occ_expiry_rejects_too_short_symbol() -> None:
    with pytest.raises(ValueError, match="Not a valid OCC"):
        parse_occ_expiry("SPY123")


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_hedge_journal(tmp_path, monkeypatch):
    monkeypatch.setattr("src.hedge.HEDGE_TRADES_PATH", tmp_path / "hedge_trades.csv")


def test_record_and_load_hedge_trade_roundtrip() -> None:
    record_hedge_trade({
        "timestamp_utc": "2026-09-10T12:00:00+00:00",
        "trade_date": "2026-09-10",
        "action": "open",
        "contract_symbol": "SPY261002P00720000",
        "underlying_symbol": "SPY",
        "option_type": "put",
        "strike_price": 720.0,
        "expiration_date": "2026-10-02",
        "qty": 2,
        "side": "buy",
        "position_intent": "buy_to_open",
        "reference_mid_price": 3.15,
        "filled_avg_price": None,
        "notional_covered": 144000.0,
        "gross_equity_exposure": 150000.0,
        "estimated_cost": 630.0,
        "underlying_price_at_trade": 758.0,
        "order_id": "",
        "status": "DRY_RUN",
        "dry_run": True,
        "note": "",
    })
    loaded = load_hedge_trades()
    assert len(loaded) == 1
    assert loaded.iloc[0]["contract_symbol"] == "SPY261002P00720000"


def test_load_hedge_trades_empty_when_no_file() -> None:
    loaded = load_hedge_trades()
    assert loaded.empty


# ---------------------------------------------------------------------------
# update_hedge_fills -- must not repeat finding #24's duplication bug
# ---------------------------------------------------------------------------


class _FakeBroker:
    def __init__(self, order_state: dict) -> None:
        self._state = order_state
        self.calls = 0

    def get_order(self, order_id: str) -> dict:
        self.calls += 1
        return self._state


def _submitted_row(order_id: str = "opt-order-1") -> dict:
    return {
        "timestamp_utc": "2026-09-10T12:00:00+00:00",
        "trade_date": "2026-09-10",
        "action": "open",
        "contract_symbol": "SPY261002P00720000",
        "underlying_symbol": "SPY",
        "option_type": "put",
        "strike_price": 720.0,
        "expiration_date": "2026-10-02",
        "qty": 1,
        "side": "buy",
        "position_intent": "buy_to_open",
        "reference_mid_price": 2.70,
        "filled_avg_price": None,
        "notional_covered": 72000.0,
        "gross_equity_exposure": 88000.0,
        "estimated_cost": 270.0,
        "underlying_price_at_trade": 758.0,
        "order_id": order_id,
        "status": "pending_new",
        "dry_run": False,
        "note": "",
    }


def test_pending_hedge_order_gets_one_correction_when_filled() -> None:
    record_hedge_trade(_submitted_row())
    broker = _FakeBroker({"status": "filled", "filled_avg_price": "2.71"})
    written = update_hedge_fills(broker)
    assert written == 1
    trades = load_hedge_trades()
    assert (trades["status"] == "filled").sum() == 1
    assert trades.iloc[-1]["filled_avg_price"] == pytest.approx(2.71)


def test_already_filled_hedge_order_is_not_repolled() -> None:
    """The exact regression finding #24 was about, applied to the hedge journal."""
    record_hedge_trade(_submitted_row())
    broker = _FakeBroker({"status": "filled", "filled_avg_price": "2.71"})

    first = update_hedge_fills(broker)
    second = update_hedge_fills(broker)

    assert first == 1
    assert second == 0
    assert broker.calls == 1


def test_dry_run_hedge_plans_are_never_polled() -> None:
    row = _submitted_row()
    row["order_id"] = ""
    row["dry_run"] = True
    record_hedge_trade(row)
    broker = _FakeBroker({"status": "filled", "filled_avg_price": "2.71"})
    assert update_hedge_fills(broker) == 0
    assert broker.calls == 0


def test_still_open_hedge_order_is_left_alone() -> None:
    record_hedge_trade(_submitted_row())
    broker = _FakeBroker({"status": "pending_new", "filled_avg_price": None})
    assert update_hedge_fills(broker) == 0


def test_fill_update_note_is_clean_not_literal_nan() -> None:
    """An empty note round-trips through CSV as NaN, which is truthy in
    Python -- ``nan or ""`` keeps the NaN. Caught live on the first real
    hedge fill (a literal "nan [fill update]" note)."""
    record_hedge_trade(_submitted_row())  # note="" -> read back as NaN
    broker = _FakeBroker({"status": "filled", "filled_avg_price": "2.71"})
    update_hedge_fills(broker)
    trades = load_hedge_trades()
    assert trades.iloc[-1]["note"] == "[fill update]"
