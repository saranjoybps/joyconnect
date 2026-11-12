"""Node implementations. Each handler takes a NodeCtx and returns a NodeResult (outputs by name, as lists of items).

Core nodes follow n8n's documented behavior (docs.n8n.io core nodes); where we deliberately differ it is noted in
docs/decisions.md (no Code-based Sort, no binary data, no disk or URL sub-workflows).
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import random
import socket
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import httpx

from app.agent.tools import BoundTool, pick_connection
from app.connectors.base import classify_status
from app.connectors.registry import get_manifest
from app.workflows import conditions
from app.workflows.engine import Item, NodeCtx, NodeError, NodeResult, to_items
from app.workflows.expressions import to_text
from app.workflows.registry import MAIN

Handler = Callable[[NodeCtx], Awaitable[NodeResult]]
HANDLERS: dict[str, Handler] = {}
MAX_RESPONSE_BYTES = 5_000_000


def handler(*types: str):
    def deco(fn: Handler) -> Handler:
        for t in types:
            HANDLERS[t] = fn
        return fn
    return deco


def _json(item: Item) -> dict[str, Any]:
    j = item.get("json")
    return j if isinstance(j, dict) else {}


def get_path(data: Any, path: str, dot: bool = True) -> Any:
    if not dot:
        return data.get(path) if isinstance(data, dict) else None
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def set_path(data: dict[str, Any], path: str, value: Any, dot: bool = True) -> None:
    parts = path.split(".") if dot else [path]
    cur = data
    for p in parts[:-1]:
        if not isinstance(cur.get(p), dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def _only(outputs: dict[str, list[Item]]) -> NodeResult:
    return NodeResult(outputs)


# ------------------------------------------------------------------------------------------ triggers

@handler("manual_trigger", "schedule_trigger", "webhook_trigger", "error_trigger")
async def trigger(ctx: NodeCtx) -> NodeResult:
    items = ctx.items or [{"json": {}}]
    if ctx.node["type"] == "schedule_trigger" and not ctx.items:
        items = [{"json": {"timestamp": ctx.svc.now().isoformat(timespec="seconds")}}]
    return _only({MAIN: items})


# ------------------------------------------------------------------------------------------ flow

@handler("if")
async def if_node(ctx: NodeCtx) -> NodeResult:
    yes: list[Item] = []
    no: list[Item] = []
    conds = ctx.params.get("conditions")
    for i, item in enumerate(ctx.items):
        (yes if conditions.evaluate(conds, lambda v, i=i: ctx.eval(v, i)) else no).append(item)
    return _only({"true": yes, "false": no})


@handler("filter")
async def filter_node(ctx: NodeCtx) -> NodeResult:
    conds = ctx.params.get("conditions")
    kept = [item for i, item in enumerate(ctx.items) if conditions.evaluate(conds, lambda v, i=i: ctx.eval(v, i))]
    return _only({MAIN: kept})


@handler("switch")
async def switch(ctx: NodeCtx) -> NodeResult:
    outs = ctx.nt.output_names(ctx.params)
    result: dict[str, list[Item]] = {o: [] for o in outs}
    mode = ctx.params.get("mode", "rules")
    fallback = ctx.params.get("fallback", "none")
    for i, item in enumerate(ctx.items):
        if mode == "expression":
            idx = ctx.eval(ctx.params.get("expression"), i)
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                raise NodeError(f"the Switch expression must return an output number, got {idx!r}", "invalid")
            if not 0 <= idx < len(outs):
                raise NodeError(f"the Switch expression returned output {idx}, but there are {len(outs)}", "invalid")
            result[f"case_{idx}"].append(item)
            continue
        hits = [n for n, rule in enumerate(ctx.params.get("rules") or [])
                if conditions.evaluate(rule.get("conditions"), lambda v, i=i: ctx.eval(v, i))]
        if not ctx.params.get("all_matching"):
            hits = hits[:1]
        if hits:
            for n in hits:
                result[f"case_{n}"].append(item)
        elif fallback == "extra":
            result["fallback"].append(item)
        elif fallback == "output_0":
            result["case_0"].append(item)
    return _only(result)


def _merge_dicts(a: dict, b: dict, clash: str) -> dict:
    if clash == "prefer_input1":
        return {**b, **a}
    if clash == "add_suffix":
        out = {k: v for k, v in a.items() if k not in b}
        out.update({k: v for k, v in b.items() if k not in a})
        for k in a.keys() & b.keys():
            out[f"{k}_1"], out[f"{k}_2"] = a[k], b[k]
        return out
    return {**a, **b}


@handler("merge")
async def merge(ctx: NodeCtx) -> NodeResult:
    a, b = ctx.inputs.get("input1", []), ctx.inputs.get("input2", [])
    p = ctx.params
    mode, clash = p.get("mode", "append"), p.get("clash", "prefer_input2")
    if mode == "append":
        return _only({MAIN: a + b})
    if mode == "choose_branch":
        choose = p.get("choose", "input1")
        return _only({MAIN: a if choose == "input1" else b if choose == "input2" else [{"json": {}}]})
    if mode == "combine_by_position":
        out = [{"json": _merge_dicts(_json(x), _json(b[i]), clash)} if i < len(b) else x for i, x in enumerate(a)]
        return _only({MAIN: out})
    if mode == "all_combinations":
        return _only({MAIN: [{"json": _merge_dicts(_json(x), _json(y), clash)} for x in a for y in b]})
    if mode == "combine_by_fields":
        pairs = [(f.get("field1"), f.get("field2") or f.get("field1")) for f in (p.get("fields") or []) if f.get("field1")]
        if not pairs:
            raise NodeError("Merge: add at least one field to match on", "invalid")
        first_only = p.get("multiple_matches") == "first"

        def key(item: Item, side: int):
            return tuple(json.dumps(get_path(_json(item), pr[side]), sort_keys=True, default=str) for pr in pairs)

        index2: dict[tuple, list[int]] = {}
        for j, y in enumerate(b):
            index2.setdefault(key(y, 1), []).append(j)
        matched1, matched2, joined = set(), set(), []
        for i, x in enumerate(a):
            hits = index2.get(key(x, 0), [])
            hits = hits[:1] if first_only else hits
            for j in hits:
                matched1.add(i)
                matched2.add(j)
                joined.append({"json": _merge_dicts(_json(x), _json(b[j]), clash)})
        un1 = [x for i, x in enumerate(a) if i not in matched1]
        un2 = [y for j, y in enumerate(b) if j not in matched2]
        kind = p.get("output_type", "matches")
        out = {"matches": joined, "non_matches": un1 + un2, "everything": joined + un1 + un2,
               "input1": joined + un1, "input2": joined + un2}.get(kind)
        if out is None:
            raise NodeError(f"Merge: unknown output type '{kind}'", "invalid")
        return _only({MAIN: out})
    raise NodeError(f"Merge: unknown mode '{mode}'", "invalid")


@handler("loop_over_items")
async def loop(ctx: NodeCtx) -> NodeResult:
    """First arrival: take all items and hand out the first batch. Later arrivals are the batch coming back from
    the loop body; when none are left the collected results go out of `done`."""
    st = ctx.state
    size = max(1, int(ctx.param("batch_size", 0, 1) or 1))
    if not st.get("loop_started"):
        st.update(loop_started=True, remaining=list(ctx.items), results=[])
    else:
        st["results"].extend(ctx.items)
    if st["remaining"]:
        batch, st["remaining"] = st["remaining"][:size], st["remaining"][size:]
        return _only({"loop": batch, "done": []})
    results = st["results"]
    st.update(loop_started=False, remaining=[], results=[])
    return _only({"loop": [], "done": results})


@handler("wait")
async def wait(ctx: NodeCtx) -> NodeResult:
    if ctx.resumed:
        return _only({MAIN: ctx.items})
    p = ctx.params
    if p.get("mode") == "time":
        raw = ctx.param("resume_at", 0)
        try:
            until = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            raise NodeError(f"Wait: '{raw}' is not a date-time (use ISO 8601)", "invalid")
        until = until if until.tzinfo else until.replace(tzinfo=timezone.utc)
    else:
        mult = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}[p.get("unit", "seconds")]
        try:
            seconds = float(ctx.param("amount", 0, 0)) * mult
        except (TypeError, ValueError):
            raise NodeError("Wait: the amount must be a number", "invalid")
        until = ctx.svc.now() + timedelta(seconds=max(seconds, 0))
    if until <= ctx.svc.now():
        return _only({MAIN: ctx.items})
    return NodeResult({MAIN: ctx.items}, wait_until=until)


@handler("stop_and_error")
async def stop_and_error(ctx: NodeCtx) -> NodeResult:
    if ctx.params.get("error_type") == "object":
        obj = ctx.param("error_object", 0, {})
        raise NodeError(str((obj or {}).get("message", "Workflow stopped")), "stop", details=obj)
    raise NodeError(str(ctx.param("message", 0, "Workflow stopped")), "stop")


@handler("execute_sub_workflow")
async def sub_workflow(ctx: NodeCtx) -> NodeResult:
    wid = ctx.param("workflow_id", 0)
    if not wid:
        raise NodeError("Sub-workflow: choose a workflow", "invalid")
    engine = ctx.svc.engine
    if ctx.params.get("mode") == "each_item":
        out: list[Item] = []
        for item in ctx.items:
            out += await engine.run_nested(ctx.run, str(wid), [item])
        return _only({MAIN: out})
    return _only({MAIN: await engine.run_nested(ctx.run, str(wid), ctx.items)})


# ------------------------------------------------------------------------------------------ data

def _coerce(value: Any, typ: str) -> Any:
    try:
        if typ == "string":
            return value if isinstance(value, str) else json.dumps(value, default=str) if isinstance(
                value, (dict, list)) else "" if value is None else str(value)
        if typ == "number":
            return float(value) if not isinstance(value, (int, float)) or isinstance(value, bool) else value
        if typ == "boolean":
            return value if isinstance(value, bool) else str(value).lower() in ("true", "1", "yes")
        if typ in ("array", "object"):
            v = json.loads(value) if isinstance(value, str) else value
            if (typ == "array") != isinstance(v, list) or (typ == "object") != isinstance(v, dict):
                raise ValueError
            return v
    except (TypeError, ValueError):
        raise NodeError(f"Edit Fields: cannot convert {value!r} to {typ}", "invalid")
    return value


@handler("set")
async def set_fields(ctx: NodeCtx) -> NodeResult:
    p = ctx.params
    dot = p.get("dot_notation", True)
    out: list[Item] = []
    for i, item in enumerate(ctx.items):
        base = {} if p.get("keep_only_set") else json.loads(json.dumps(_json(item)))
        if p.get("mode") == "json":
            val = ctx.eval(p.get("json", {}), i)
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except json.JSONDecodeError as exc:
                    raise NodeError(f"Edit Fields: the JSON is not valid ({exc.msg})", "invalid")
            if not isinstance(val, dict):
                raise NodeError("Edit Fields: the JSON must be an object", "invalid")
            base.update(val)
        else:
            for f in p.get("fields") or []:
                name = ctx.eval(f.get("name"), i)
                if not name:
                    raise NodeError("Edit Fields: a field has no name", "invalid")
                value = ctx.eval(f.get("value"), i)
                set_path(base, str(name), _coerce(value, f.get("type", "auto")), dot)
        out.append({"json": base})
    return _only({MAIN: out})


@handler("aggregate")
async def aggregate(ctx: NodeCtx) -> NodeResult:
    p = ctx.params
    items = ctx.items
    if p.get("mode") == "all_item_data":
        include = p.get("include", "all")
        fields = p.get("include_fields") or []
        rows = []
        for it in items:
            j = _json(it)
            if include == "specified":
                j = {k: j[k] for k in fields if k in j}
            elif include == "except":
                j = {k: v for k, v in j.items() if k not in fields}
            rows.append(j)
        return _only({MAIN: [{"json": {p.get("destination_field") or "data": rows}}]})
    out: dict[str, Any] = {}
    specs = p.get("fields") or []
    if not specs:
        raise NodeError("Aggregate: choose at least one field", "invalid")
    renames = [s.get("rename") or s["field"] for s in specs]
    if len(set(renames)) != len(renames):
        raise NodeError("Aggregate: give each aggregated field a different output name", "invalid")
    for s, target in zip(specs, renames):
        vals = [get_path(_json(it), s["field"]) for it in items]
        if not p.get("keep_missing"):
            vals = [v for v in vals if v is not None]
        if p.get("merge_lists"):
            vals = [x for v in vals for x in (v if isinstance(v, list) else [v])]
        set_path(out, target, vals)
    return _only({MAIN: [{"json": out}]})


@handler("split_out")
async def split_out(ctx: NodeCtx) -> NodeResult:
    p = ctx.params
    field = p.get("field")
    if not field:
        raise NodeError("Split Out: choose the field to split", "invalid")
    dest = p.get("destination_field") or field
    include = p.get("include", "none")
    out: list[Item] = []
    for it in ctx.items:
        j = _json(it)
        values = get_path(j, field)
        if values is None:
            continue
        if not isinstance(values, list):
            raise NodeError(f"Split Out: '{field}' is not a list", "invalid")
        for v in values:
            row: dict[str, Any] = {}
            if include == "all":
                row = {k: x for k, x in j.items() if k != field.split(".")[0]}
            elif include == "selected":
                row = {k: j[k] for k in p.get("include_fields") or [] if k in j}
            row[dest] = v
            out.append({"json": row})
    return _only({MAIN: out})


@handler("sort")
async def sort(ctx: NodeCtx) -> NodeResult:
    items = list(ctx.items)
    if ctx.params.get("type") == "random":
        random.shuffle(items)
        return _only({MAIN: items})
    specs = ctx.params.get("fields") or []
    if not specs:
        raise NodeError("Sort: choose at least one field", "invalid")
    for s in reversed(specs):           # stable sorts, least significant key first
        desc = s.get("order") == "desc"
        present = [i for i in items if get_path(_json(i), s["field"]) is not None]
        absent = [i for i in items if get_path(_json(i), s["field"]) is None]
        try:
            present.sort(key=lambda i: get_path(_json(i), s["field"]), reverse=desc)
        except TypeError:
            present.sort(key=lambda i: str(get_path(_json(i), s["field"])), reverse=desc)
        items = present + absent
    return _only({MAIN: items})


@handler("limit")
async def limit(ctx: NodeCtx) -> NodeResult:
    n = int(ctx.param("max_items", 0, 1))
    items = ctx.items
    return _only({MAIN: items[:n] if ctx.params.get("keep", "first") == "first" else (items[-n:] if n else [])})


@handler("respond_to_webhook")
async def respond(ctx: NodeCtx) -> NodeResult:
    p, items = ctx.params, ctx.items
    mode = p.get("respond_with", "first_item")
    resp: dict[str, Any] = {"status": int(p.get("response_code") or 200), "headers": ctx.eval(p.get("headers") or {})}
    if mode == "all_items":
        resp["body"] = [_json(i) for i in items]
    elif mode == "first_item":
        resp["body"] = _json(items[0]) if items else {}
    elif mode in ("json", "text"):
        resp["body"] = ctx.eval(p.get("body"), 0)
        resp["text"] = mode == "text"
    elif mode == "redirect":
        url = str(ctx.eval(p.get("redirect_url"), 0) or "")
        if not url.startswith(("http://", "https://")):
            raise NodeError("Respond to Webhook: the redirect URL must start with http:// or https://", "invalid")
        resp.update(status=int(p.get("response_code") or 302), redirect=url)
    else:
        resp["body"] = None
    return NodeResult({MAIN: items}, response=resp)


# ------------------------------------------------------------------------------------------ HTTP request

async def _resolve(host: str) -> list[str]:                  # replaced in tests
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [i[4][0] for i in infos]


async def check_public_host(url: str, allow_private: bool) -> None:
    """SSRF guard: users can point this node anywhere, so refuse loopback, private, link-local (cloud metadata)
    and reserved addresses unless ALLOW_PRIVATE_HTTP_HOSTS is on. (A DNS answer can change between this check and
    the request; redirects are not followed, which closes the easy bypass.)"""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise NodeError("HTTP Request: the URL must start with http:// or https://", "invalid")
    if allow_private:
        return
    try:
        addrs = await _resolve(parts.hostname)
    except OSError:
        raise NodeError(f"HTTP Request: could not look up {parts.hostname}", "server", retryable=True)
    for a in addrs:
        ip = ipaddress.ip_address(a)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise NodeError("HTTP Request: that address is private or internal, which is blocked.", "blocked")


@handler("http_request")
async def http_request(ctx: NodeCtx) -> NodeResult:
    p = ctx.params
    out: list[Item] = []
    for i, _item in enumerate(ctx.items):
        method = str(ctx.eval(p.get("method", "GET"), i)).upper()
        url = str(ctx.eval(p.get("url"), i) or "")
        await check_public_host(url, ctx.svc.settings.allow_private_http_hosts)
        kwargs: dict[str, Any] = {
            "headers": {str(k): to_text(v) for k, v in (ctx.eval(p.get("headers") or {}, i) or {}).items()
                        if v is not None},
            "params": {str(k): to_text(v) for k, v in (ctx.eval(p.get("query") or {}, i) or {}).items()
                       if v is not None}}
        body_type, body = p.get("body_type", "none"), ctx.eval(p.get("body"), i)
        if body_type == "json" and body is not None:
            kwargs["json"] = json.loads(body) if isinstance(body, str) else body
        elif body_type == "form" and isinstance(body, dict):
            kwargs["data"] = body
        elif body_type == "raw" and body is not None:
            kwargs["content"] = str(body).encode()
        timeout = float(p.get("timeout_ms") or 30000) / 1000
        try:
            resp = await ctx.svc.http.request(method, url, timeout=timeout, follow_redirects=False, **kwargs)
        except httpx.TimeoutException:
            raise NodeError("HTTP Request: the server did not answer in time", "timeout", retryable=True)
        except httpx.HTTPError as exc:
            raise NodeError(f"HTTP Request: could not reach the server ({type(exc).__name__})", "server",
                            retryable=True)
        if len(resp.content) > MAX_RESPONSE_BYTES:
            raise NodeError("HTTP Request: the response is larger than 5 MB", "limit")
        if resp.status_code >= 400 and not p.get("ignore_errors"):
            kind = classify_status(resp.status_code)
            raise NodeError(f"HTTP Request failed with status {resp.status_code}", kind,
                            retryable=kind in ("rate_limit", "server"), details={"status": resp.status_code})
        fmt = p.get("response_format", "autodetect")
        ctype = resp.headers.get("content-type", "")
        try:
            data: Any = resp.json() if fmt == "json" or (fmt == "autodetect" and "json" in ctype) else resp.text
        except ValueError:
            data = resp.text
        row = data if isinstance(data, dict) else {"data": data}
        if p.get("ignore_errors"):
            row = {**row, "statusCode": resp.status_code}
        out.append({"json": row})
    return _only({MAIN: out})


# ------------------------------------------------------------------------------------------ app nodes

def _app_items(result: Any) -> list[Item]:
    if isinstance(result, list):
        return [{"json": r if isinstance(r, dict) else {"value": r}} for r in result]
    return [{"json": result if isinstance(result, dict) else {"value": result}}]


@handler("__app__")
async def app_node(ctx: NodeCtx) -> NodeResult:
    """One node per connector tool. Runs once per input item with that item's parameters, through the same
    ToolExecutor the chat agent uses (token refresh, scope check, error classification, read retries)."""
    nt = ctx.nt
    manifest = get_manifest(nt.connector or "")
    tool = next((t for t in (manifest.tools if manifest else []) if t.name == nt.tool), None)
    if manifest is None or tool is None:
        raise NodeError(f"{nt.name} is no longer available", "not_found")
    db, user = ctx.svc.db, ctx.run.user_id
    cid = ctx.node.get("connection_id")
    if not cid:
        raise NodeError(f"Choose which connected {manifest.name} account this step should use.", "auth")
    rows = await db.select("connections", {"id": cid, "user_id": user})
    if not rows:
        raise NodeError(f"The {manifest.name} connection for this step no longer exists. Pick another one.", "auth")
    if rows[0]["provider"] != manifest.id or rows[0].get("status") != "active":
        raise NodeError(f"{manifest.name} needs to be reconnected on the Connections page.", "auth")
    own = rows[0]
    active = await db.select("connections", {"user_id": user, "status": "active"}, order="created_at.desc")
    bound = BoundTool(manifest, tool, pick_connection(manifest, tool, own, active), own)
    props = list(tool.parameters.get("properties", {}))
    out: list[Item] = []
    for i, _item in enumerate(ctx.items):
        args = {k: ctx.eval(ctx.params.get(k), i) for k in props}
        ok, result, _ms = await ctx.svc.executor.execute_timed(bound, args)
        if not ok:
            kind = (result or {}).get("kind", "other") if isinstance(result, dict) else "other"
            raise NodeError(str((result or {}).get("error", "failed")) if isinstance(result, dict) else "failed",
                            kind, retryable=kind in ("server", "rate_limit"))
        out += _app_items(result)
    return _only({MAIN: out})
