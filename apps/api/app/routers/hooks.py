"""Public webhook endpoint: /api/hooks/{path}. No login: the unguessable path (and optional header secret) is the
credential. Only published workflows answer."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

router = APIRouter(prefix="/api", tags=["webhooks"])
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]


@router.api_route("/hooks/{path}", methods=METHODS, include_in_schema=False)
async def hook(path: str, request: Request) -> Response:
    triggers = request.app.state.triggers
    limit = request.app.state.settings.webhook_max_body_bytes
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        return JSONResponse({"error": "payload too large"}, status_code=413)
    body = await request.body()
    res = await triggers.handle_webhook(path, request.method, dict(request.headers), dict(request.query_params), body)
    headers = dict(res.headers)
    if res.allow:
        headers["Allow"] = res.allow
    if res.redirect:
        return RedirectResponse(res.redirect, status_code=res.status, headers=headers)
    if res.text:
        # Always text/plain: a workflow's output must never be served as HTML from our origin.
        return PlainTextResponse("" if res.body is None else str(res.body), status_code=res.status, headers=headers)
    return JSONResponse(res.body, status_code=res.status, headers=headers)
