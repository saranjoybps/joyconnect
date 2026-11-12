"""Memory.

Short-term: the last `history_window` messages plus a rolling summary of everything older (Summarizer).
Long-term: durable facts about the user in a pgvector table (MemoryService): extracted after a chat, retrieved
at the start of the next one, listed/edited/deleted on the Memory page, and switchable off per user.

What is allowed in: names, preferences, recurring tasks, key identifiers. What is not: secrets, tool output,
one-off requests, other people's data. The extraction step only ever reads the user's and the assistant's own
messages plus the arguments of tool calls, never raw tool output, so a poisoned document cannot write memory.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Protocol

from app.agent.llm import LLM, LLMError, LLMResult
from app.agent.policy import redact_args, scrub
from app.agent.usage import Usage, UsageLog, usage_of
from app.core.config import Settings
from app.core.logging import _PATTERNS as SECRET_PATTERNS
from app.db.client import Database

log = logging.getLogger(__name__)
KINDS = ("fact", "preference", "task", "identifier")
MAX_LEN = 300
_SECRETISH = re.compile(r"(?i)\b(password|passwd|secret|api[ _-]?key|access[ _-]?token|refresh[ _-]?token|private key|"
                        r"credit card|card number|cvv|ssn|social security)\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    """text-embedding-3-small (1536 dimensions). A paid call: only used by the running app, never by tests."""

    def __init__(self, settings: Settings):
        from openai import AsyncOpenAI

        if not settings.openai_api_key:
            raise LLMError("OPENAI_API_KEY is not set")
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_embedding_model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import openai

        try:
            resp = await self._client.embeddings.create(model=self._model, input=texts)
        except openai.OpenAIError as exc:
            raise LLMError(type(exc).__name__) from exc
        return [d.embedding for d in resp.data]


def clean_memory(kind: Any, content: Any) -> tuple[str, str] | None:
    """A memory the extraction step proposed, validated; None if it must not be stored."""
    if kind not in KINDS or not isinstance(content, str):
        return None
    text = " ".join(content.split())
    if not 3 <= len(text) <= MAX_LEN:
        return None
    if scrub(text) != text or _SECRETISH.search(text) or any(p.search(text) for p in SECRET_PATTERNS):
        return None                       # token-shaped strings and credential talk are never stored
    return kind, text


EXTRACT_PROMPT = """You maintain a small long-term memory about ONE user of an assistant.
From the conversation below, extract only DURABLE facts worth remembering in future chats:
- who they are (name, role, company), their preferences (language, tone, format, time zone),
- recurring tasks or routines,
- key identifiers they rely on (for example the name and id of their main spreadsheet, their default Slack channel).

Do NOT store: one-off requests, the content of documents/emails/messages, anything that came from a tool result,
secrets, passwords, tokens, financial or health details, or personal data about other people.
Each memory is ONE short sentence in the third person ("Prefers answers in bullet points.").
Return JSON only, exactly: {"memories":[{"kind":"fact|preference|task|identifier","content":"..."}]}
At most 5. Return {"memories":[]} if nothing qualifies."""

SUMMARY_PROMPT = """Update the running summary of an assistant conversation.
Keep: what the user wants, decisions made, names and ids that matter, what was done in which app, open questions.
Drop: pleasantries and raw data. Plain text, under 250 words, no lists of raw tool output.
Return only the new summary."""


async def _complete(llm: LLM, system: str, user: str) -> tuple[str, LLMResult | None]:
    out: list[str] = []
    result: LLMResult | None = None
    async for part in llm.stream([{"role": "system", "content": system}, {"role": "user", "content": user}], []):
        if isinstance(part, LLMResult):
            result = part
        else:
            out.append(part)
    return ("".join(out) or (result.content if result else "")), result


def transcript(rows: list[dict[str, Any]], limit_chars: int = 6000) -> str:
    """The user's and assistant's own words plus tool-call names with redacted arguments. Tool OUTPUT is left out."""
    lines: list[str] = []
    for r in rows:
        if r["role"] == "user" and r.get("content"):
            lines.append(f"USER: {scrub(str(r['content']))[:800]}")
        elif r["role"] == "assistant":
            if r.get("content"):
                lines.append(f"ASSISTANT: {scrub(str(r['content']))[:800]}")
            for c in r.get("tool_calls") or []:
                try:
                    args = redact_args(json.loads(c["function"]["arguments"] or "{}"))
                except json.JSONDecodeError:
                    args = {}
                lines.append(f"ASSISTANT CALLED {c['function']['name']} {json.dumps(args, ensure_ascii=False)[:300]}")
    text = "\n".join(lines)
    return text[-limit_chars:]


class MemoryService:
    def __init__(self, db: Database, embedder_factory: Callable[[], Embedder] | None,
                 llm_factory: Callable[[], LLM], settings: Settings):
        self.db, self.settings = db, settings
        self._embedder_factory, self._llm_factory = embedder_factory, llm_factory
        self.usage = UsageLog(db, settings)

    # ------------------------------------------------------------------ the switch

    async def enabled(self, user_id: str) -> bool:
        """On unless the user turned it off. If the tables are missing (migration 0008 not applied) memory is off."""
        try:
            rows = await self.db.select("user_settings", {"user_id": user_id})
        except Exception:  # noqa: BLE001
            log.warning("memory is unavailable (migration 0008 applied?)")
            return False
        return bool(rows[0]["memory_enabled"]) if rows else True

    async def set_enabled(self, user_id: str, on: bool) -> bool:
        rows = await self.db.select("user_settings", {"user_id": user_id})
        if rows:
            await self.db.update("user_settings", {"user_id": user_id}, {"memory_enabled": on})
        else:
            await self.db.insert("user_settings", {"user_id": user_id, "memory_enabled": on})
        return on

    # ------------------------------------------------------------------ the Memory page

    async def list(self, user_id: str) -> list[dict[str, Any]]:
        rows = await self.db.select("memories", {"user_id": user_id}, order="created_at.desc", limit=500)
        return [self.public(r) for r in rows]

    @staticmethod
    def public(r: dict[str, Any]) -> dict[str, Any]:
        return {"id": r["id"], "kind": r.get("kind", "fact"), "content": r["content"],
                "created_at": r.get("created_at"), "updated_at": r.get("updated_at")}

    async def add(self, user_id: str, kind: str, content: str, conversation_id: str | None = None) -> dict[str, Any]:
        cleaned = clean_memory(kind, content)
        if cleaned is None:
            raise ValueError("That cannot be saved as a memory (too short or long, or it looks like a secret).")
        kind, text = cleaned
        if len(await self.db.select("memories", {"user_id": user_id}, limit=self.settings.memory_max_per_user + 1)) \
                >= self.settings.memory_max_per_user:
            raise ValueError(f"You have reached the limit of {self.settings.memory_max_per_user} memories. Delete some first.")
        row = await self.db.insert("memories", {
            "user_id": user_id, "kind": kind, "content": text, "embedding": await self._embed_one(text),
            "source_conversation_id": conversation_id})
        return self.public(row)

    async def update(self, user_id: str, memory_id: str, content: str | None, kind: str | None) -> dict[str, Any] | None:
        rows = await self.db.select("memories", {"id": memory_id, "user_id": user_id})
        if not rows:
            return None
        cleaned = clean_memory(kind or rows[0].get("kind", "fact"), content if content is not None else rows[0]["content"])
        if cleaned is None:
            raise ValueError("That cannot be saved as a memory (too short or long, or it looks like a secret).")
        values: dict[str, Any] = {"kind": cleaned[0], "content": cleaned[1]}
        if cleaned[1] != rows[0]["content"]:
            values["embedding"] = await self._embed_one(cleaned[1])
        won = await self.db.update("memories", {"id": memory_id, "user_id": user_id}, values)
        return self.public(won[0]) if won else None

    async def delete(self, user_id: str, memory_id: str) -> bool:
        return bool(await self.db.delete("memories", {"id": memory_id, "user_id": user_id}))

    async def delete_all(self, user_id: str) -> int:
        return len(await self.db.delete("memories", {"user_id": user_id}))

    # ------------------------------------------------------------------ retrieval at chat start

    async def retrieve(self, user_id: str, query: str) -> list[str]:
        """The memories most relevant to what the user just said. Cheap when there are none (no embedding call)."""
        if not query.strip() or not await self.enabled(user_id):
            return []
        try:
            if not await self.db.select("memories", {"user_id": user_id}, limit=1):
                return []
            vec = await self._embed_one(query)
            if vec is not None:
                hits = await self.db.rpc("match_memories", {
                    "p_user_id": user_id, "query_embedding": vec, "match_count": self.settings.memory_top_k})
                if hits:
                    return [h["content"] for h in hits]
            recent = await self.db.select("memories", {"user_id": user_id}, order="created_at.desc",
                                          limit=self.settings.memory_top_k)
            return [r["content"] for r in recent]
        except Exception:  # noqa: BLE001 — a memory problem must never stop a chat
            log.warning("memory retrieval failed")
            return []

    # ------------------------------------------------------------------ extraction after a chat

    async def extract(self, user_id: str, conversation_id: str) -> list[dict[str, Any]]:
        if not self.settings.memory_extraction or not await self.enabled(user_id):
            return []
        try:
            rows = await self.db.select("messages", {"conversation_id": conversation_id, "user_id": user_id},
                                        order="seq.asc")
            text = transcript(rows[-14:])
            if not text.strip():
                return []
            raw, result = await _complete(self._llm_factory(), EXTRACT_PROMPT, text)
            await self.usage.record(user_id, conversation_id, "memory",
                                    usage_of(result.usage if result else None, [{"c": text}], raw, []))
            proposals = self._parse(raw)
            stored = []
            for kind, content in proposals[:5]:
                try:
                    if await self._is_duplicate(user_id, content):
                        continue
                    stored.append(await self.add(user_id, kind, content, conversation_id))
                except ValueError:
                    break                      # the per-user limit
            return stored
        except Exception as exc:  # noqa: BLE001
            log.warning("memory extraction failed: %s", type(exc).__name__)
            return []

    @staticmethod
    def _parse(raw: str) -> list[tuple[str, str]]:
        m = re.search(r"\{.*\}", raw or "", re.S)
        if not m:
            return []
        try:
            items = json.loads(m.group(0)).get("memories", [])
        except (json.JSONDecodeError, AttributeError):
            return []
        out = []
        for it in items if isinstance(items, list) else []:
            cleaned = clean_memory(it.get("kind") if isinstance(it, dict) else None,
                                   it.get("content") if isinstance(it, dict) else None)
            if cleaned:
                out.append(cleaned)
        return out

    async def _is_duplicate(self, user_id: str, content: str) -> bool:
        key = content.lower().strip(" .")
        for r in await self.db.select("memories", {"user_id": user_id}, limit=self.settings.memory_max_per_user + 1):
            if r["content"].lower().strip(" .") == key:
                return True
        vec = await self._embed_one(content)
        if vec is None:
            return False
        near = await self.db.rpc("match_memories", {"p_user_id": user_id, "query_embedding": vec,
                                                    "match_count": 1, "match_threshold": 0.92})
        return bool(near)

    async def _embed_one(self, text: str) -> list[float] | None:
        if self._embedder_factory is None:
            return None
        try:
            return (await self._embedder_factory().embed([text]))[0]
        except Exception:  # noqa: BLE001 — store the text anyway; it is still listed and used by recency
            log.warning("embedding failed")
            return None


class Summarizer:
    """Rolling summary of the older part of a conversation (short-term memory)."""

    def __init__(self, db: Database, llm_factory: Callable[[], LLM], settings: Settings):
        self.db, self.settings, self._llm_factory = db, settings, llm_factory
        self.usage = UsageLog(db, settings)

    async def maybe_summarize(self, user_id: str, conversation: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
        """If more than `history_window` messages are not yet summarized, fold the older ones into the summary.
        Returns the (possibly updated) conversation row fields: summary, summary_upto."""
        upto = int(conversation.get("summary_upto") or 0)
        fresh = [r for r in rows if int(r.get("seq") or 0) > upto]
        window, keep = self.settings.history_window, self.settings.history_keep_after_summary
        out = {"summary": conversation.get("summary"), "summary_upto": upto}
        if len(fresh) <= window:
            return out
        cut = len(fresh) - keep
        while cut < len(fresh) and fresh[cut]["role"] != "user":       # keep whole turns together
            cut += 1
        if cut <= 0 or cut >= len(fresh):
            return out
        older = fresh[:cut]
        try:
            prior = f"Current summary:\n{out['summary']}\n\n" if out["summary"] else ""
            new, result = await _complete(self._llm_factory(), SUMMARY_PROMPT, prior + "New messages:\n" + transcript(older))
            await self.usage.record(user_id, conversation["id"], "summary",
                                    usage_of(result.usage if result else None, [{"c": prior}], new, []))
            summary = scrub(new.strip())[:2500]
            if not summary:
                return out
            upto_seq = int(older[-1]["seq"])
            await self.db.update("conversations", {"id": conversation["id"], "user_id": user_id},
                                 {"summary": summary, "summary_upto": upto_seq})
            return {"summary": summary, "summary_upto": upto_seq}
        except Exception as exc:  # noqa: BLE001 — fall back to the plain window
            log.warning("conversation summary failed: %s", type(exc).__name__)
            return out
