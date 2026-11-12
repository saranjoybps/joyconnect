"""LLM client: OpenAI Chat Completions with streamed tool calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

from app.core.config import Settings


@dataclass
class LLMResult:
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)  # OpenAI message tool_calls shape
    usage: dict[str, int] | None = None  # {"prompt_tokens", "completion_tokens"} when the provider reports it


class LLMError(Exception):
    pass


class LLM(Protocol):
    def stream(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AsyncIterator[str | LLMResult]:
        """Yields text deltas (str), then exactly one LLMResult."""
        ...


class OpenAIChat:
    def __init__(self, settings: Settings):
        from openai import AsyncOpenAI

        if not settings.openai_api_key:
            raise LLMError("OPENAI_API_KEY is not set")
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model
        self._parallel = settings.llm_parallel_tool_calls

    async def stream(self, messages, tools):
        import openai

        kwargs: dict[str, Any] = {"model": self._model, "messages": messages, "stream": True,
                                  "stream_options": {"include_usage": True}}
        if tools:
            # Parallel calls are allowed by default; every call is still validated and policy-checked one by one
            # on our side. Set LLM_PARALLEL_TOOL_CALLS=false to go back to one call per turn.
            kwargs.update(tools=tools, parallel_tool_calls=self._parallel)
        content: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        usage: dict[str, int] | None = None
        try:
            stream = await self._client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if getattr(chunk, "usage", None):
                    usage = {"prompt_tokens": chunk.usage.prompt_tokens or 0,
                             "completion_tokens": chunk.usage.completion_tokens or 0}
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    content.append(delta.content)
                    yield delta.content
                for tc in delta.tool_calls or []:
                    slot = calls.setdefault(tc.index, {"id": "", "type": "function",
                                                       "function": {"name": "", "arguments": ""}})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["function"]["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["function"]["arguments"] += tc.function.arguments
        except openai.OpenAIError as exc:
            raise LLMError(type(exc).__name__) from exc
        yield LLMResult(content="".join(content), tool_calls=[calls[i] for i in sorted(calls)], usage=usage)
