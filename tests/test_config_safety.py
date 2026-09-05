"""Tests for the paper-trading safety interlock.

These are the most important tests in the project. If they pass, the system
cannot be configured to talk to a live-money endpoint. If any of them fail,
nothing else should be run.
"""

from __future__ import annotations

import pytest

from src.config import (
    ALPACA_PAPER_ENDPOINT,
    PAPER_TRADING_ONLY,
    LiveTradingBlockedError,
    assert_paper_only,
    load_broker_config,
)


def test_paper_only_flag_is_hardcoded_true() -> None:
    """The project-level invariant must never be flipped."""
    assert PAPER_TRADING_ONLY is True


def test_paper_endpoint_accepted() -> None:
    """The documented paper endpoint with a true flag is the only happy path."""
    assert_paper_only(ALPACA_PAPER_ENDPOINT, "true")


@pytest.mark.parametrize(
    "live_url",
    [
        "https://api.alpaca.markets",
        "http://api.alpaca.markets",
        "https://api.alpaca.markets/",
        "  https://api.alpaca.markets  ",
    ],
)
def test_known_live_endpoints_are_rejected(live_url: str) -> None:
    """Alpaca's live endpoint must be refused, including trailing/whitespace forms."""
    with pytest.raises(LiveTradingBlockedError, match="LIVE trading endpoint"):
        assert_paper_only(live_url, "true")


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://paper-api.alpaca.market",  # typo: missing 's'
        "https://paper-api.alpaca.markets.evil.com",  # prefix-match attack
        "https://evil.com/paper-api.alpaca.markets",  # substring attack
        "https://data.alpaca.markets",
        "not-a-url",
    ],
)
def test_unrecognised_endpoints_fail_closed(url: str) -> None:
    """Anything not exactly the paper endpoint is rejected.

    This is the reason the check is an allow-list rather than a deny-list: a
    typo, a look-alike domain, or a new endpoint must fail, not pass by virtue
    of merely not appearing on a block list.
    """
    with pytest.raises(LiveTradingBlockedError):
        assert_paper_only(url, "true")


@pytest.mark.parametrize("flag", [None, "", "false", "False", "0", "no", "TRUE1", "yes"])
def test_paper_flag_must_be_true(flag: str | None) -> None:
    """Even on the correct endpoint, the explicit flag must say 'true'."""
    with pytest.raises(LiveTradingBlockedError, match="PAPER_TRADING_ONLY"):
        assert_paper_only(ALPACA_PAPER_ENDPOINT, flag)


@pytest.mark.parametrize("flag", ["true", "TRUE", "True", "  true  "])
def test_paper_flag_accepts_case_and_whitespace(flag: str) -> None:
    """The flag comparison is case- and whitespace-insensitive."""
    assert_paper_only(ALPACA_PAPER_ENDPOINT, flag)


def test_load_broker_config_blocks_live_before_reading_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A live endpoint must be refused *before* any credential is read.

    Ordering matters: the interlock runs first so that a misconfigured
    environment never loads a secret into process memory.
    """
    monkeypatch.setenv("ALPACA_BASE_URL", "https://api.alpaca.markets")
    monkeypatch.setenv("PAPER_TRADING_ONLY", "true")
    monkeypatch.setenv("ALPACA_API_KEY_ID", "should-never-be-read")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "should-never-be-read")

    with pytest.raises(LiveTradingBlockedError):
        load_broker_config(dotenv_path=tmp_path / "nonexistent.env")


def test_load_broker_config_requires_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A correctly-configured paper endpoint still needs credentials."""
    monkeypatch.setenv("ALPACA_BASE_URL", ALPACA_PAPER_ENDPOINT)
    monkeypatch.setenv("PAPER_TRADING_ONLY", "true")
    monkeypatch.setenv("ALPACA_API_KEY_ID", "")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "")

    with pytest.raises(RuntimeError, match="credentials missing"):
        load_broker_config(dotenv_path=tmp_path / "nonexistent.env")


def test_broker_config_never_reveals_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Credentials must not appear in repr or str, which reach logs and tracebacks."""
    secret_key = "SUPER-SECRET-KEY-ID-12345"
    secret_val = "SUPER-SECRET-VALUE-67890"
    monkeypatch.setenv("ALPACA_BASE_URL", ALPACA_PAPER_ENDPOINT)
    monkeypatch.setenv("PAPER_TRADING_ONLY", "true")
    monkeypatch.setenv("ALPACA_API_KEY_ID", secret_key)
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", secret_val)

    config = load_broker_config(dotenv_path=tmp_path / "nonexistent.env")

    assert config.api_key_id == secret_key  # still usable
    for rendered in (repr(config), str(config), f"{config}"):
        assert secret_key not in rendered
        assert secret_val not in rendered
        assert "redacted" in rendered
