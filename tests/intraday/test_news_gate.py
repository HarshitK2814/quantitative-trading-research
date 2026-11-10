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


def test_titles_from_both_yfinance_shapes_and_skip_untitled():
    data = {"AAPL": [{"content": {"title": "New shape"}}, {"title": "Old shape"},
                     {"content": {}}, {"id": 1}]}
    out = fetch_headlines(["AAPL"], ticker_news=lambda s: data["AAPL"])
    assert out == {"AAPL": ["New shape", "Old shape"]}


def test_crypto_mapped_for_call_keyed_with_slash():
    calls = []

    def fake(sym):
        calls.append(sym)
        return [{"title": "BTC up"}]

    out = fetch_headlines(["BTC/USD"], ticker_news=fake)
    assert calls == ["BTC-USD"] and out == {"BTC/USD": ["BTC up"]}


def test_failing_symbol_is_none_others_ok():
    def fake(sym):
        if sym == "BAD":
            raise RuntimeError("down")
        return []

    out = fetch_headlines(["AAPL", "BAD"], ticker_news=fake)
    assert out == {"AAPL": [], "BAD": None}


def test_headlines_sanitised_and_limited():
    items = [{"title": "a\n\n  b\tc"}, {"title": "x" * 500}, {"title": "third"}]
    out = fetch_headlines(["AAPL"], limit=2, ticker_news=lambda s: items)
    assert out["AAPL"][0] == "a b c"
    assert len(out["AAPL"][1]) == 200 and len(out["AAPL"]) == 2


def test_none_headlines_veto_without_calling_groq():
    def must_not_call(*a, **k):
        raise AssertionError("called")

    v = review_trade("AAPL", None, "key", post=must_not_call)
    assert v.action == "veto" and v.reason == "news unavailable"


def test_invalid_action_reason_truncated():
    v = review_trade("AAPL", ["x"], "key",
                     post=_groq(json.dumps({"action": "y" * 200})))
    assert v.action == "veto" and len(v.reason) < 100


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
