"""Multi-leg (mleg) order body, built offline with a fake _request."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import src.broker as broker_mod

LEGS = [
    {"symbol": "SPY261218P00650000", "side": "sell", "position_intent": "sell_to_open"},
    {"symbol": "SPY261218P00645000", "side": "buy", "position_intent": "buy_to_open"},
]


def _broker(sent):
    b = object.__new__(broker_mod.AlpacaPaperBroker)

    def fake_request(method, path, **kw):
        sent.append((method, path, kw))
        return {"id": "oid", "client_order_id": kw["json"].get("client_order_id", ""),
                "symbol": "", "side": "", "qty": "2", "type": "limit",
                "time_in_force": "day", "status": "accepted",
                "submitted_at": "t", "filled_qty": "0", "filled_avg_price": None,
                "order_class": "mleg"}

    b._request = fake_request
    return b


def test_spread_order_body_is_one_mleg_limit_with_two_legs():
    sent = []
    res = _broker(sent).submit_spread_order(LEGS, 2, -1.234, client_order_id="k")
    method, path, kw = sent[0]
    body = kw["json"]
    assert (method, path) == ("POST", "/v2/orders")
    assert body["order_class"] == "mleg" and body["type"] == "limit"
    assert body["limit_price"] == "-1.23" and body["qty"] == "2"
    assert body["client_order_id"] == "k" and "symbol" not in body
    assert body["legs"] == [{**lg, "ratio_qty": "1"} for lg in LEGS]
    assert res.order_id == "oid" and res.status == "accepted"


def test_spread_order_refuses_fewer_than_two_legs_or_bad_legs():
    sent = []
    b = _broker(sent)
    with pytest.raises(ValueError):
        b.submit_spread_order(LEGS[:1], 1, -1.0)
    with pytest.raises(ValueError):
        b.submit_spread_order([LEGS[0], {"symbol": "X", "side": "buy"}], 1, -1.0)
    with pytest.raises(ValueError):
        b.submit_spread_order([LEGS[0], LEGS[0]], 1, -1.0)   # no buy leg: naked
    with pytest.raises(ValueError):
        b.submit_spread_order(LEGS, 0, -1.0)
    assert sent == []


def test_order_by_client_id_uses_lookup_endpoint():
    sent = []
    b = object.__new__(broker_mod.AlpacaPaperBroker)
    b._request = lambda m, p, **kw: sent.append((m, p, kw)) or {"status": "new"}
    assert b.get_order_by_client_id("k")["status"] == "new"
    assert sent[0][:2] == ("GET", "/v2/orders:by_client_order_id")
    assert sent[0][2]["params"] == {"client_order_id": "k"}


def test_parse_ts_handles_nanoseconds_and_missing():
    ts = broker_mod._parse_ts("2026-11-10T16:29:59.123456789Z")
    assert ts == datetime(2026, 11, 10, 16, 29, 59, 123456, tzinfo=UTC)
    assert broker_mod._parse_ts(None) is None
    assert broker_mod._parse_ts("junk") is None


def test_get_orders_can_request_nested_mleg_legs():
    sent = []
    b = object.__new__(broker_mod.AlpacaPaperBroker)
    b._request = lambda m, p, **kw: sent.append(kw) or []
    b.get_orders(status="open", nested=True)
    assert sent[0]["params"]["nested"] == "true"
