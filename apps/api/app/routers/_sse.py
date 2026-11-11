"""Turn an agent event stream into an SSE response, surfacing early errors as HTTP status."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.agent.runtime import AgentError

log = logging.getLogger(__name__)


def format_sse(event: dict[str, Any]) -> str:
    return f"event: {event['event']}\ndata: {json.dumps(event['data'], default=str)}\n\n"


async def sse_response(events: AsyncIterator[dict[str, Any]]) -> StreamingResponse:
    # Pull the first event before committing to a 200, so validation errors map to HTTP codes.
    try:
        first = await events.__anext__()
    except AgentError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    except StopAsyncIteration:
        first = None

    async def body():
        if first is not None:
            yield format_sse(first)
        try:
            async for ev in events:
                yield format_sse(ev)
        except AgentError as exc:
            yield format_sse({"event": "error", "data": {"message": str(exc)}})
            yield format_sse({"event": "done", "data": {}})
        except Exception as exc:  # noqa: BLE001
            log.exception("agent stream failed: %s", type(exc).__name__)
            yield format_sse({"event": "error", "data": {"message": "Something went wrong."}})
            yield format_sse({"event": "done", "data": {}})

    return StreamingResponse(body(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
