"""Tests for news fetch and Groq gate (no network)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from src.intraday.groq_gate import review_trade
from src.intraday.news import fetch_headlines


def _resp(payload, status=200):
    return SimpleNamespace(status_code=status, json=lambda: payload,
                           raise_for_status=lambda: None)


def _groq(content):
    return lambda *a, **k: _resp({"choices": [{"message": {"content": content}}]})


def test_headlines_grouped_by_symbol_and_crypto_slash_removed():
    seen = {}

    def fake_get(url, params, headers, timeout):
        seen["symbols"] = params["symbols"]
        return _resp({"news": [{"headline": "Up", "symbols": ["AAPL"]},
                               {"headline": "BTC jumps", "symbols": ["BTCUSD"]}]})

    out = fetch_headlines(["AAPL", "BTC/USD"], "k", "s", get=fake_get)
    assert seen["symbols"] == "AAPL,BTCUSD"
    assert out["AAPL"] == ["Up"] and out["BTC/USD"] == ["BTC jumps"]


def test_headlines_error_returns_empty():
    def boom(*a, **k):
        raise RuntimeError("down")

    assert fetch_headlines(["AAPL"], "k", "s", get=boom) == {"AAPL": []}


def test_no_headlines_means_ok_without_calling_groq():
    def must_not_call(*a, **k):
        raise AssertionError("called")

    assert review_trade("AAPL", [], "key", post=must_not_call).action == "ok"


def test_veto_and_reduce_parsed():
    v = review_trade("AAPL", ["Fraud probe"], "key",
                     post=_groq(json.dumps({"action": "veto", "reason": "fraud"})))
    assert v.action == "veto" and v.reason == "fraud"
    v = review_trade("AAPL", ["Mixed"], "key",
                     post=_groq(json.dumps({"action": "reduce", "reason": "mixed"})))
    assert v.action == "reduce"


def test_failures_fail_safe_to_veto():
    assert review_trade("AAPL", ["x"], "", post=_groq("{}")).action == "veto"   # no key
    assert review_trade("AAPL", ["x"], "key", post=_groq("not json")).action == "veto"
    assert review_trade("AAPL", ["x"], "key",
                        post=_groq(json.dumps({"action": "buy_more"}))).action == "veto"

    def boom(*a, **k):
        raise RuntimeError("429")

    assert review_trade("AAPL", ["x"], "key", post=boom).action == "veto"
