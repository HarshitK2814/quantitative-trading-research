"""Groq LLM news check. It can only veto or halve a BUY, never add risk."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"
_VALID = {"ok", "reduce", "veto"}

PROMPT = (
    "You are a risk reviewer for a paper-trading bot that wants to BUY {symbol}. "
    "Headlines:\n{headlines}\n\n"
    'Reply with JSON only: {{"action": "ok"|"reduce"|"veto", "reason": "<12 words"}}. '
    "veto = serious negative news (fraud, bankruptcy, guidance cut, hack, "
    "regulatory action). reduce = mixed or uncertain. ok = nothing alarming. "
    "You may not recommend buying more."
)


@dataclass(frozen=True)
class Verdict:
    """Gate decision."""

    action: str  # "ok" | "reduce" | "veto"
    reason: str


def review_trade(
    symbol: str, headlines: list[str] | None, api_key: str, post=requests.post
) -> Verdict:
    """Ask Groq to review a buy. Any failure returns a veto (fail safe)."""
    if headlines is None:
        return Verdict("veto", "news unavailable")
    if not headlines:
        return Verdict("ok", "no news")
    if not api_key:
        return Verdict("veto", "GROQ_API_KEY missing")
    try:
        resp = post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": MODEL,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": PROMPT.format(
                    symbol=symbol,
                    headlines="\n".join(f"- {h}" for h in headlines))}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = json.loads(resp.json()["choices"][0]["message"]["content"])
        action = data.get("action")
        if action not in _VALID:
            return Verdict("veto", f"invalid action {action!r}"[:60])
        return Verdict(action, str(data.get("reason", ""))[:200])
    except Exception as exc:
        logger.warning("groq gate failed: %s", exc)
        return Verdict("veto", "gate unavailable")
