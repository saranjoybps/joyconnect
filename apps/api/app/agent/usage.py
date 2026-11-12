"""Token and cost accounting: per-run caps and per-user daily limits.

Usage comes from the model's own report (OpenAI stream usage). When a provider reports none, it is estimated
from text length (about 4 characters per token) so the caps still bite.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.db.client import Database

log = logging.getLogger(__name__)


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, other: "Usage") -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens


def estimate_tokens(value: Any) -> int:
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    return max(1, len(text) // 4)


def usage_of(reported: dict[str, int] | None, messages: list[dict[str, Any]], content: str, tool_calls: list[Any]) -> Usage:
    if reported and (reported.get("prompt_tokens") or reported.get("completion_tokens")):
        return Usage(int(reported.get("prompt_tokens", 0)), int(reported.get("completion_tokens", 0)))
    return Usage(estimate_tokens(messages), estimate_tokens(content) + (estimate_tokens(tool_calls) if tool_calls else 0))


def cost_usd(settings: Settings, u: Usage) -> float:
    return (u.prompt_tokens * settings.llm_price_input_per_m + u.completion_tokens * settings.llm_price_output_per_m) / 1_000_000


class RunBudget:
    """Caps for one run (one user message and the tool loop it starts)."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.usage = Usage()

    def add(self, u: Usage) -> None:
        self.usage.add(u)

    @property
    def cost(self) -> float:
        return cost_usd(self.settings, self.usage)

    def exceeded(self) -> str | None:
        s = self.settings
        if s.max_run_tokens and self.usage.total >= s.max_run_tokens:
            return f"I stopped because this task used about {self.usage.total:,} tokens, which is the per-task limit."
        if s.max_run_cost_usd and self.cost >= s.max_run_cost_usd:
            return f"I stopped because this task reached its cost limit (about ${self.cost:.2f})."
        return None


class UsageLog:
    """Writes llm_usage rows and answers 'how many tokens today'. Never breaks chat if the table is missing."""

    def __init__(self, db: Database, settings: Settings):
        self.db, self.settings = db, settings

    async def record(self, user_id: str, conversation_id: str | None, purpose: str, u: Usage) -> None:
        try:
            await self.db.insert("llm_usage", {
                "user_id": user_id, "conversation_id": conversation_id, "purpose": purpose,
                "prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens,
                "cost_usd": round(cost_usd(self.settings, u), 6)})
        except Exception:  # noqa: BLE001 — accounting must never break a chat
            log.warning("could not record llm usage")

    async def tokens_today(self, user_id: str) -> int:
        now = datetime.now(timezone.utc)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            rows = await self.db.select_since("llm_usage", {"user_id": user_id}, "created_at", midnight, limit=5000)
        except Exception:  # noqa: BLE001
            return 0
        return sum(int(r.get("prompt_tokens", 0)) + int(r.get("completion_tokens", 0)) for r in rows)
