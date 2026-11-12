"""Step 2: executor, worker queue, expressions in nodes, branching, loops, errors, retries, approvals,
run-from-here and test-node. All HTTP is mocked; there is no LLM involved."""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from app.workflows import engine as engine_mod
from app.workflows import handlers
from app.workflows.runner import ExecutionError
from app.workflows.runtime import build_workflow_runtime
from tests.conftest import USER_A, USER_B, auth
from tests.test_agent import SHEET, connect, make_client  # noqa: F401


@pytest.fixture
async def rt(db, store, settings, monkeypatch):
    async def public(host):
        return ["93.184.216.34"]

    monkeypatch.setattr(handlers, "_resolve", public)

    async def no_sleep(seconds):
        return None

    monkeypatch.setattr(engine_mod, "_sleep", no_sleep)
    async with httpx.AsyncClient() as http:
        yield build_workflow_runtime(db, store, http, settings)


def n(nid, type_, name=None, params=None, **extra):
    node = {"id": nid, "type": type_, "name": name or nid, "parameters": params or {}}
    node.update(extra)
    return {"op": "add_node", "node": node}


def c(a, b, output="main", input_=None):
    op = {"op": "connect", "from": a, "to": b, "output": output}
    if input_:
        op["input"] = input_
    return op


async def make(rt, *ops, name="WF", settings=None, user=USER_A):
    doc = await rt.workflows.create(user, name, list(ops))
    if settings:
        doc, _, _ = await rt.workflows.patch(user, doc["id"], doc["version"],
                                             [{"op": "set_settings", "settings": settings}])
    return doc["id"]


async def drain(rt, limit=200):
    done = 0
    while await rt.executions.process_one("test-worker"):
        done += 1
        assert done < limit, "queue never drained"
    return done


async def run(rt, wid, **kw):
    row = await rt.executions.start(USER_A, wid, **kw)
    await drain(rt)
    return (await rt.executions.get(USER_A, row["id"]))


def rec(result, name, run_index=-1, status=None):
    rows = [r for r in result["nodes"] if r["node_name"] == name and (status is None or r["status"] == status)]
    return rows[run_index] if rows else None


def out(result, name, output="main", run_index=-1):
    r = rec(result, name, run_index, status="success")
    return [i["json"] for i in (r["output"] or {}).get(output, [])] if r else None


def statuses(result):
    return {r["node_name"]: r["status"] for r in result["nodes"]}


TRIG = n("t", "manual_trigger", "Start")


# ------------------------------------------------------------------ the basics: items, expressions

async def test_linear_flow_items_and_expressions(rt):
    wid = await make(rt, TRIG,
                     n("s", "set", "Make", {"fields": [{"name": "email", "value": "{{ $json.name.toLowerCase() }}@x.com"},
                                                       {"name": "n", "value": "{{ $json.n * 2 }}", "type": "number"}]}),
                     n("l", "limit", "First", {"max_items": 1}),
                     n("s2", "set", "Final", {"fields": [{"name": "from_make", "value": '{{ $node["Make"].json.email }}'},
                                                         {"name": "start", "value": '{{ $("Start").first().json.name }}'}]}),
                     c("t", "s"), c("s", "l"), c("l", "s2"))
    res = await run(rt, wid, trigger_data=[{"name": "Ada", "n": 2}, {"name": "Bob", "n": 3}])
    assert res["execution"]["status"] == "success"
    assert out(res, "Make") == [{"name": "Ada", "n": 4, "email": "ada@x.com"}, {"name": "Bob", "n": 6, "email": "bob@x.com"}]
    assert out(res, "First") == [{"name": "Ada", "n": 4, "email": "ada@x.com"}]
    final = out(res, "Final")[0]
    assert final["from_make"] == "ada@x.com" and final["start"] == "Ada"
    assert all(r["duration_ms"] is not None and r["attempts"] == 1 for r in res["nodes"])
    assert res["execution"]["finished_at"] and res["execution"]["cost_usd"] == 0


async def test_each_node_records_input_and_output(rt):
    wid = await make(rt, TRIG, n("s", "set", "S", {"fields": [{"name": "a", "value": 1}]}), c("t", "s"))
    res = await run(rt, wid, trigger_data={"x": 1})
    r = rec(res, "S")
    assert r["input"]["main"][0]["json"] == {"x": 1}
    assert r["output"]["main"][0]["json"] == {"x": 1, "a": 1}


async def test_secrets_in_item_data_are_masked_in_records(rt):
    wid = await make(rt, TRIG)
    res = await run(rt, wid, trigger_data={"api_key": "sk-live-abcdef", "note": "Bearer abcdefghijklmnop1234"})
    j = rec(res, "Start")["output"]["main"][0]["json"]
    assert j["api_key"] == "[REDACTED]" and "abcdefghijklmnop1234" not in str(j)


# ------------------------------------------------------------------ branching

async def test_if_routes_items_and_skips_the_empty_branch(rt):
    cond = {"items": [{"left": "{{ $json.n }}", "type": "number", "op": "gt", "right": 5}]}
    wid = await make(rt, TRIG, n("i", "if", "Big?", {"conditions": cond}),
                     n("hi", "set", "High", {"fields": [{"name": "tier", "value": "high"}]}),
                     n("lo", "set", "Low", {"fields": [{"name": "tier", "value": "low"}]}),
                     c("t", "i"), c("i", "hi", "true"), c("i", "lo", "false"))
    res = await run(rt, wid, trigger_data=[{"n": 9}, {"n": 1}, {"n": 7}])
    assert out(res, "High") == [{"n": 9, "tier": "high"}, {"n": 7, "tier": "high"}]
    assert out(res, "Low") == [{"n": 1, "tier": "low"}]
    # only one side has data: the other is skipped
    res = await run(rt, wid, trigger_data=[{"n": 9}])
    assert statuses(res)["High"] == "success" and "Low" not in statuses(res)


async def test_switch_rules_fallback_and_expression_mode(rt):
    rules = [{"conditions": {"items": [{"left": "{{ $json.k }}", "type": "string", "op": "equals", "right": "a"}]}},
             {"conditions": {"items": [{"left": "{{ $json.k }}", "type": "string", "op": "equals", "right": "b"}]}}]
    wid = await make(rt, TRIG, n("sw", "switch", "Route", {"rules": rules, "fallback": "extra"}),
                     n("a", "set", "A", {"fields": [{"name": "r", "value": "A"}]}),
                     n("b", "set", "B", {"fields": [{"name": "r", "value": "B"}]}),
                     n("o", "set", "Other", {"fields": [{"name": "r", "value": "other"}]}),
                     c("t", "sw"), c("sw", "a", "case_0"), c("sw", "b", "case_1"), c("sw", "o", "fallback"))
    res = await run(rt, wid, trigger_data=[{"k": "a"}, {"k": "b"}, {"k": "z"}, {"k": "a"}])
    assert [i["k"] for i in out(res, "A")] == ["a", "a"]
    assert out(res, "B") == [{"k": "b", "r": "B"}] and out(res, "Other") == [{"k": "z", "r": "other"}]

    wid = await make(rt, TRIG, n("sw", "switch", "R", {"mode": "expression", "number_of_outputs": 2,
                                                       "expression": "{{ $json.i }}"}),
                     n("a", "set", "A", {}), n("b", "set", "B", {}),
                     c("t", "sw"), c("sw", "a", "case_0"), c("sw", "b", "case_1"))
    res = await run(rt, wid, trigger_data=[{"i": 1}, {"i": 0}])
    assert out(res, "A") == [{"i": 0}] and out(res, "B") == [{"i": 1}]
    res = await run(rt, wid, trigger_data=[{"i": 5}])
    assert res["execution"]["status"] == "error" and "output 5" in res["execution"]["error"]["message"]


async def test_filter_keeps_matching_items(rt):
    cond = {"items": [{"left": "{{ $json.n }}", "type": "number", "op": "gte", "right": 2}]}
    wid = await make(rt, TRIG, n("f", "filter", "Keep", {"conditions": cond}), n("s", "set", "After"),
                     c("t", "f"), c("f", "s"))
    res = await run(rt, wid, trigger_data=[{"n": 1}, {"n": 2}, {"n": 3}])
    assert out(res, "Keep") == [{"n": 2}, {"n": 3}]
    res = await run(rt, wid, trigger_data=[{"n": 1}])
    assert out(res, "Keep") == [] and "After" not in statuses(res) or statuses(res).get("After") == "skipped"
    assert res["execution"]["status"] == "success"


async def test_merge_waits_for_both_inputs_and_modes(rt):
    cond = {"items": [{"left": "{{ $json.n }}", "type": "number", "op": "gt", "right": 1}]}
    base = [TRIG, n("i", "if", "If", {"conditions": cond}),
            n("hi", "set", "Hi", {"fields": [{"name": "side", "value": "hi"}]}),
            n("lo", "set", "Lo", {"fields": [{"name": "side", "value": "lo"}]}), c("t", "i"),
            c("i", "hi", "true"), c("i", "lo", "false")]
    wid = await make(rt, *base, n("m", "merge", "Join", {"mode": "append"}),
                     c("hi", "m", input_="input1"), c("lo", "m", input_="input2"))
    res = await run(rt, wid, trigger_data=[{"n": 5}, {"n": 0}])
    assert sorted(i["side"] for i in out(res, "Join")) == ["hi", "lo"]
    # one side empty: the merge still runs with what it has
    res = await run(rt, wid, trigger_data=[{"n": 5}])
    assert out(res, "Join") == [{"n": 5, "side": "hi"}]

    pos = await make(rt, *base, n("m", "merge", "Join", {"mode": "combine_by_position", "clash": "add_suffix"}),
                     c("hi", "m", input_="input1"), c("lo", "m", input_="input2"))
    res = await run(rt, pos, trigger_data=[{"n": 5}, {"n": 6}, {"n": 0}])
    assert out(res, "Join")[0]["side_1"] == "hi" and out(res, "Join")[0]["side_2"] == "lo"

    allc = await make(rt, *base, n("m", "merge", "Join", {"mode": "all_combinations"}),
                      c("hi", "m", input_="input1"), c("lo", "m", input_="input2"))
    res = await run(rt, allc, trigger_data=[{"n": 5}, {"n": 6}, {"n": 0}])
    assert len(out(res, "Join")) == 2          # 2 x 1

    pick = await make(rt, *base, n("m", "merge", "Join", {"mode": "choose_branch", "choose": "input2"}),
                      c("hi", "m", input_="input1"), c("lo", "m", input_="input2"))
    res = await run(rt, pick, trigger_data=[{"n": 5}, {"n": 0}])
    assert out(res, "Join") == [{"n": 0, "side": "lo"}]


async def test_merge_by_matching_fields(rt):
    def wf(output_type, **extra):
        return [TRIG, n("a", "set", "A", {"mode": "json", "json": '{"rows": 1}'}),
                n("m", "merge", "Join", {"mode": "combine_by_fields", "fields": [{"field1": "id", "field2": "uid"}],
                                         "output_type": output_type, **extra}), c("t", "a")]
    # Feed the two inputs from split items through two Sets keyed differently.
    ops = [TRIG,
           n("l", "set", "Left", {"mode": "json", "json": '{"id": 1}'}),
           n("r", "set", "Right", {"mode": "json", "json": '{"uid": 1, "extra": "x"}'}),
           c("t", "l"), c("t", "r")]
    for out_type, expected in [("matches", 1), ("everything", 1), ("input1", 1), ("non_matches", 0)]:
        wid = await make(rt, *ops, n("m", "merge", "Join", {"mode": "combine_by_fields", "output_type": out_type,
                                                            "fields": [{"field1": "id", "field2": "uid"}]}),
                         c("l", "m", input_="input1"), c("r", "m", input_="input2"))
        res = await run(rt, wid)
        assert len(out(res, "Join")) == expected, out_type
    assert out(res, "Join") == [] and res["execution"]["status"] == "success"
    wid = await make(rt, *ops, n("m", "merge", "Join", {"mode": "combine_by_fields", "fields": [
        {"field1": "id", "field2": "uid"}]}), c("l", "m", input_="input1"), c("r", "m", input_="input2"))
    assert out(await run(rt, wid), "Join") == [{"id": 1, "uid": 1, "extra": "x"}]
    wid = await make(rt, *ops, n("m", "merge", "Join", {"mode": "combine_by_fields"}),
                     c("l", "m", input_="input1"), c("r", "m", input_="input2"))
    assert "at least one field" in (await run(rt, wid))["execution"]["error"]["message"]


# ------------------------------------------------------------------ loops

async def test_loop_over_items_runs_the_body_per_batch_and_collects_results(rt):
    wid = await make(rt, TRIG, n("lp", "loop_over_items", "Loop", {"batch_size": 2}),
                     n("b", "set", "Body", {"fields": [{"name": "done", "value": True}]}),
                     n("after", "aggregate", "Collect", {"mode": "all_item_data"}),
                     c("t", "lp"), c("lp", "b", "loop"), c("b", "lp"), c("lp", "after", "done"))
    res = await run(rt, wid, trigger_data=[{"i": k} for k in range(5)])
    assert res["execution"]["status"] == "success"
    assert len([r for r in res["nodes"] if r["node_name"] == "Body"]) == 3          # batches of 2, 2, 1
    rows = out(res, "Collect")[0]["data"]
    assert [r["i"] for r in rows] == [0, 1, 2, 3, 4] and all(r["done"] for r in rows)


async def test_loop_whose_body_returns_nothing_still_finishes(rt):
    drop = {"items": [{"left": "{{ $json.i }}", "type": "number", "op": "lt", "right": 0}]}
    wid = await make(rt, TRIG, n("lp", "loop_over_items", "Loop", {"batch_size": 1}),
                     n("f", "filter", "DropAll", {"conditions": drop}),
                     n("after", "set", "After", {"fields": [{"name": "finished", "value": True}]}),
                     c("t", "lp"), c("lp", "f", "loop"), c("f", "lp"), c("lp", "after", "done"))
    res = await run(rt, wid, trigger_data=[{"i": 1}, {"i": 2}])
    assert res["execution"]["status"] == "success"
    assert len([r for r in res["nodes"] if r["node_name"] == "DropAll"]) == 2


async def test_endless_cycle_is_stopped(rt, settings):
    settings.workflow_max_node_runs = 25
    wid = await make(rt, TRIG, n("a", "set", "A", {}), n("b", "set", "B", {}), c("t", "a"), c("a", "b"), c("b", "a"))
    res = await run(rt, wid)
    assert res["execution"]["status"] == "error" and "endless loop" in res["execution"]["error"]["message"]


# ------------------------------------------------------------------ data nodes

async def test_aggregate_split_sort_limit(rt):
    wid = await make(rt, TRIG,
                     n("ag", "aggregate", "Agg", {"fields": [{"field": "name", "rename": "names"}, {"field": "n"}]}),
                     n("sp", "split_out", "Split", {"field": "names", "destination_field": "name"}),
                     n("so", "sort", "Sort", {"fields": [{"field": "name", "order": "desc"}]}),
                     n("li", "limit", "Last", {"max_items": 2, "keep": "last"}),
                     c("t", "ag"), c("ag", "sp"), c("sp", "so"), c("so", "li"))
    res = await run(rt, wid, trigger_data=[{"name": "b", "n": 1}, {"name": "a", "n": 2}, {"name": "c", "n": 3}])
    assert out(res, "Agg") == [{"names": ["b", "a", "c"], "n": [1, 2, 3]}]
    assert out(res, "Split") == [{"name": "b"}, {"name": "a"}, {"name": "c"}]
    assert out(res, "Sort") == [{"name": "c"}, {"name": "b"}, {"name": "a"}]
    assert out(res, "Last") == [{"name": "b"}, {"name": "a"}]


async def test_set_json_mode_keep_only_and_dot_notation(rt):
    wid = await make(rt, TRIG,
                     n("s", "set", "S", {"mode": "json", "json": '{"user": {"id": {{ $json.id }}}}', "keep_only_set": True}),
                     n("d", "set", "Dots", {"fields": [{"name": "a.b.c", "value": "{{ $json.user.id }}", "type": "string"}]}),
                     c("t", "s"), c("s", "d"))
    res = await run(rt, wid, trigger_data={"id": 7, "drop": "me"})
    assert out(res, "S") == [{"user": {"id": 7}}]
    assert out(res, "Dots") == [{"user": {"id": 7}, "a": {"b": {"c": "7"}}}]


async def test_sort_split_aggregate_errors_are_clear(rt):
    wid = await make(rt, TRIG, n("sp", "split_out", "Split", {"field": "x"}), c("t", "sp"))
    res = await run(rt, wid, trigger_data={"x": "notalist"})
    assert "not a list" in res["execution"]["error"]["message"] and res["execution"]["error"]["node"] == "Split"
    wid = await make(rt, TRIG, n("so", "sort", "Sort", {"type": "simple"}), c("t", "so"))
    assert "at least one field" in (await run(rt, wid))["execution"]["error"]["message"]


# ------------------------------------------------------------------ errors, retries, timeouts

async def test_stop_and_error_fails_the_run_with_the_node_name(rt):
    wid = await make(rt, TRIG, n("e", "stop_and_error", "Halt", {"message": "bad {{ $json.id }}"}), c("t", "e"))
    res = await run(rt, wid, trigger_data={"id": 4})
    err = res["execution"]["error"]
    assert res["execution"]["status"] == "error" and err["message"] == "bad 4" and err["node"] == "Halt"
    assert rec(res, "Halt")["status"] == "error" and rec(res, "Halt")["error"]["kind"] == "stop"


async def test_on_error_continue_lets_the_run_finish(rt):
    wid = await make(rt, TRIG, n("e", "stop_and_error", "Boom", {"message": "nope"}, settings={"on_error": "continue"}),
                     c("t", "e"))
    res = await run(rt, wid)      # Stop and Error has no output, so nothing continues downstream; the run succeeds
    assert res["execution"]["status"] == "success" and rec(res, "Boom")["status"] == "error"


@respx.mock
async def test_http_get_retries_only_when_asked_and_only_for_reads(rt):
    route = respx.get("https://api.example.com/x").mock(side_effect=[
        httpx.Response(503), httpx.Response(503), httpx.Response(200, json={"ok": True})])
    wid = await make(rt, TRIG, n("h", "http_request", "Call", {"url": "https://api.example.com/x"},
                                 settings={"retry_on_fail": True, "max_tries": 3}), c("t", "h"))
    res = await run(rt, wid)
    assert res["execution"]["status"] == "success" and route.call_count == 3
    assert rec(res, "Call")["attempts"] == 3 and out(res, "Call") == [{"ok": True}]

    before = route.call_count
    route.side_effect = [httpx.Response(503), httpx.Response(200, json={"ok": True})]
    wid = await make(rt, TRIG, n("h", "http_request", "Call", {"url": "https://api.example.com/x"}), c("t", "h"))
    res = await run(rt, wid)                                  # no retry_on_fail: one attempt, then fail
    assert res["execution"]["status"] == "error" and route.call_count - before == 1
    assert "503" in res["execution"]["error"]["message"] and rec(res, "Call")["attempts"] == 1


@respx.mock
async def test_http_non_retryable_error_is_not_retried(rt):
    route = respx.get("https://api.example.com/x").respond(404)
    wid = await make(rt, TRIG, n("h", "http_request", "Call", {"url": "https://api.example.com/x"},
                                 settings={"retry_on_fail": True, "max_tries": 3}), c("t", "h"))
    res = await run(rt, wid)
    assert route.call_count == 1 and res["execution"]["error"]["kind"] == "not_found"


@respx.mock
async def test_on_error_continue_with_http(rt):
    respx.get("https://api.example.com/x").respond(500)
    wid = await make(rt, TRIG, n("h", "http_request", "Call", {"url": "https://api.example.com/x"},
                                 settings={"on_error": "continue"}),
                     n("s", "set", "Handle", {"fields": [{"name": "msg", "value": "{{ $json.error.message }}"}]}),
                     c("t", "h"), c("h", "s"))
    res = await run(rt, wid)
    assert res["execution"]["status"] == "success"
    assert rec(res, "Call")["status"] == "error" and "500" in out(res, "Handle")[0]["msg"]


@respx.mock
async def test_http_ignore_errors_returns_status(rt):
    respx.get("https://api.example.com/x").respond(404, json={"m": "gone"})
    wid = await make(rt, TRIG, n("h", "http_request", "Call", {"url": "https://api.example.com/x", "ignore_errors": True}),
                     c("t", "h"))
    assert out(await run(rt, wid), "Call") == [{"m": "gone", "statusCode": 404}]


async def test_node_timeout(rt, monkeypatch):
    async def slow(ctx):
        await asyncio.sleep(1)

    monkeypatch.setitem(handlers.HANDLERS, "limit", slow)
    wid = await make(rt, TRIG, n("l", "limit", "Slow", {"max_items": 1}, settings={"timeout_ms": 100}), c("t", "l"))
    res = await run(rt, wid)
    assert res["execution"]["error"]["kind"] == "timeout" and "timed out" in res["execution"]["error"]["message"]


async def test_a_crashing_node_fails_the_run_not_the_worker(rt, monkeypatch):
    async def crash(ctx):
        raise RuntimeError("secret-token-123 leaked in a traceback")

    monkeypatch.setitem(handlers.HANDLERS, "limit", crash)
    wid = await make(rt, TRIG, n("l", "limit", "Crash", {"max_items": 1}), c("t", "l"))
    res = await run(rt, wid)
    assert res["execution"]["status"] == "error" and "secret-token" not in str(res["execution"]["error"])
    assert res["execution"]["error"]["kind"] == "internal"


async def test_expression_errors_name_the_node(rt):
    wid = await make(rt, TRIG, n("s", "set", "Bad", {"fields": [{"name": "x", "value": "{{ $json.a.__class__ }}"}]}),
                     c("t", "s"))
    res = await run(rt, wid, trigger_data={"a": 1})
    assert res["execution"]["error"]["kind"] == "expression" and res["execution"]["error"]["node"] == "Bad"


async def test_cost_cap_stops_the_run(rt, monkeypatch):
    real = handlers.HANDLERS["set"]

    async def costly(ctx):
        ctx.add_cost(0.6)
        return await real(ctx)

    monkeypatch.setitem(handlers.HANDLERS, "set", costly)
    wid = await make(rt, TRIG, n("a", "set", "A"), n("b", "set", "B"), n("c3", "set", "C"),
                     c("t", "a"), c("a", "b"), c("b", "c3"), settings={"cost_cap_usd": 1.0})
    res = await run(rt, wid)
    assert res["execution"]["status"] == "error" and res["execution"]["error"]["kind"] == "cost_cap"
    assert "C" not in statuses(res) and float(res["execution"]["cost_usd"]) == pytest.approx(1.2)


async def test_disabled_nodes_pass_data_through(rt):
    wid = await make(rt, TRIG, n("s", "set", "Off", {"fields": [{"name": "x", "value": 1}]}, disabled=True),
                     n("l", "limit", "After", {"max_items": 5}), c("t", "s"), c("s", "l"))
    res = await run(rt, wid, trigger_data={"a": 1})
    assert statuses(res)["Off"] == "skipped" and out(res, "After") == [{"a": 1}]


# ------------------------------------------------------------------ sub-workflows

async def test_sub_workflow_runs_and_returns_items(rt):
    child = await make(rt, n("t", "manual_trigger", "In"), n("s", "set", "Double",
                       {"fields": [{"name": "n", "value": "{{ $json.n * 2 }}", "type": "number"}]}), c("t", "s"), name="Child")
    parent = await make(rt, TRIG, n("sub", "execute_sub_workflow", "Call", {"workflow_id": child, "mode": "all_items"}),
                        c("t", "sub"))
    res = await run(rt, parent, trigger_data=[{"n": 1}, {"n": 2}])
    assert res["execution"]["status"] == "success" and out(res, "Call") == [{"n": 2}, {"n": 4}]
    nested = await rt.executions.list(USER_A, child)
    assert nested[0]["mode"] == "sub_workflow" and nested[0]["status"] == "success"

    each = await make(rt, TRIG, n("sub", "execute_sub_workflow", "Call", {"workflow_id": child, "mode": "each_item"}),
                      c("t", "sub"))
    assert out(await run(rt, each, trigger_data=[{"n": 5}, {"n": 6}]), "Call") == [{"n": 10}, {"n": 12}]
    assert len(await rt.executions.list(USER_A, child)) == 3 and True


async def test_sub_workflow_errors(rt):
    wid = await make(rt, TRIG, n("sub", "execute_sub_workflow", "Call", {"workflow_id": "nope"}), c("t", "sub"))
    assert "not found" in (await run(rt, wid))["execution"]["error"]["message"]
    other = await make(rt, TRIG, user=USER_B)
    wid = await make(rt, TRIG, n("sub", "execute_sub_workflow", "Call", {"workflow_id": other}), c("t", "sub"))
    assert "not found" in (await run(rt, wid))["execution"]["error"]["message"]          # not someone else's
    wid = await make(rt, TRIG)
    doc = await rt.workflows.get(USER_A, wid)
    await rt.workflows.patch(USER_A, wid, doc["version"], [n("sub", "execute_sub_workflow", "Me", {"workflow_id": wid}),
                                                           c("t", "sub")])
    assert "call itself" in (await run(rt, wid))["execution"]["error"]["message"]


# ------------------------------------------------------------------ HTTP node safety and webhook response

@respx.mock
async def test_http_request_blocks_private_addresses(rt, monkeypatch):
    async def private(host):
        return ["169.254.169.254"]

    monkeypatch.setattr(handlers, "_resolve", private)
    route = respx.get("http://metadata.internal/latest").respond(200, text="secret")
    wid = await make(rt, TRIG, n("h", "http_request", "Call", {"url": "http://metadata.internal/latest"}), c("t", "h"))
    res = await run(rt, wid)
    assert res["execution"]["error"]["kind"] == "blocked" and not route.called
    for ip in ("127.0.0.1", "10.1.2.3", "192.168.0.9", "::1", "fd00::1"):
        async def one(host, ip=ip):
            return [ip]

        monkeypatch.setattr(handlers, "_resolve", one)
        res = await run(rt, wid)
        assert res["execution"]["error"]["kind"] == "blocked", ip
    wid = await make(rt, TRIG, n("h", "http_request", "Call", {"url": "ftp://x/y"}), c("t", "h"))
    assert "http://" in (await run(rt, wid))["execution"]["error"]["message"]


@respx.mock
async def test_http_request_does_not_follow_redirects_and_sends_body(rt):
    route = respx.post("https://api.example.com/in").respond(302, headers={"location": "http://169.254.169.254/"})
    wid = await make(rt, TRIG, n("h", "http_request", "Call", {
        "method": "POST", "url": "https://api.example.com/in", "body_type": "json",
        "body": {"name": "{{ $json.name }}"}, "headers": {"X-Id": "{{ $json.id }}"}, "query": {"q": "1"}}, ),
        c("t", "h"), settings={"auto_approve": "writes"})
    res = await run(rt, wid, trigger_data={"name": "Ada", "id": 5})
    req = route.calls[0].request
    assert req.headers["x-id"] == "5" and req.url.params["q"] == "1" and b'"Ada"' in req.read()
    assert route.call_count == 1                      # the redirect to the metadata address was NOT followed
    assert res["execution"]["status"] == "success"


async def test_respond_to_webhook_sets_the_response(rt):
    wid = await make(rt, TRIG, n("r", "respond_to_webhook", "Reply", {
        "respond_with": "json", "body": {"ok": True, "who": "{{ $json.name }}"}, "response_code": 201,
        "headers": {"X-A": "b"}}), c("t", "r"))
    res = await run(rt, wid, trigger_data={"name": "Ada"})
    assert res["execution"]["response"] == {"status": 201, "headers": {"X-A": "b"},
                                            "body": {"ok": True, "who": "Ada"}, "text": False}
    wid = await make(rt, TRIG, n("r", "respond_to_webhook", "Reply", {"respond_with": "redirect",
                                                                      "redirect_url": "javascript:alert(1)"}), c("t", "r"))
    assert "http://" in (await run(rt, wid))["execution"]["error"]["message"]


# ------------------------------------------------------------------ app nodes (connector tools)

@respx.mock
async def test_app_node_runs_per_item_with_that_items_parameters(rt, db, store):
    conn = await connect(db, store, "google_sheets")
    route = respx.get(url__regex=r".*/values/.*").mock(side_effect=lambda req: httpx.Response(
        200, json={"range": "r", "values": [[str(req.url)[-6:]]]}))
    wid = await make(rt, TRIG, n("g", "google_sheets__get_values", "Read", {
        "spreadsheet_id": SHEET, "range": "{{ $json.range }}"}, connection_id=conn["id"]), c("t", "g"))
    res = await run(rt, wid, trigger_data=[{"range": "A1:B2"}, {"range": "C3:D4"}])
    assert res["execution"]["status"] == "success" and route.call_count == 2
    assert "A1" in str(route.calls[0].request.url) and "C3" in str(route.calls[1].request.url)
    assert len(out(res, "Read")) == 2


async def test_app_node_needs_a_valid_connection(rt, db, store):
    wid = await make(rt, TRIG, n("g", "google_sheets__get_values", "Read", {"spreadsheet_id": SHEET, "range": "A1"}),
                     c("t", "g"))
    res = await run(rt, wid)
    assert res["execution"]["error"]["kind"] == "auth" and "Choose which connected" in res["execution"]["error"]["message"]
    conn = await connect(db, store, "google_sheets", status="needs_reauth")
    await rt.workflows.patch(USER_A, wid, 1, [{"op": "update_node", "id": "g", "connection_id": conn["id"]}])
    assert "reconnected" in (await run(rt, wid))["execution"]["error"]["message"]


@respx.mock
async def test_app_node_missing_scope_never_calls_the_provider(rt, db, store):
    conn = await connect(db, store, "google_sheets", scopes=[])
    route = respx.get(url__regex=r".*/values/.*").respond(200, json={})
    wid = await make(rt, TRIG, n("g", "google_sheets__get_values", "Read", {"spreadsheet_id": SHEET, "range": "A1"},
                                 connection_id=conn["id"]), c("t", "g"))
    res = await run(rt, wid)
    assert "Reconnect Google Sheets" in res["execution"]["error"]["message"] and not route.called


@respx.mock
async def test_app_node_provider_error_is_classified(rt, db, store):
    conn = await connect(db, store, "google_sheets")
    respx.get(url__regex=r".*/values/.*").respond(404, json={"error": {"message": "no sheet"}})
    wid = await make(rt, TRIG, n("g", "google_sheets__get_values", "Read", {"spreadsheet_id": SHEET, "range": "A1"},
                                 connection_id=conn["id"]), c("t", "g"))
    res = await run(rt, wid)
    assert res["execution"]["error"]["kind"] == "not_found"


# ------------------------------------------------------------------ approvals

APPEND = {"spreadsheet_id": SHEET, "range": "A:B", "values": ["{{ $json.name }}", "x"]}


async def append_flow(rt, db, store, settings=None, user=USER_A, label="acct"):
    conn = await connect(db, store, "google_sheets", user=user, label=label)
    return await make(rt, TRIG, n("g", "google_sheets__append_row", "Append", APPEND, connection_id=conn["id"]),
                      c("t", "g"), settings=settings, user=user)


@respx.mock
async def test_write_node_pauses_for_approval_then_runs_once(rt, db, store):
    route = respx.post(url__regex=r".*/values/.*:append").respond(json={"updates": {"updatedRange": "A2:B2"}})
    wid = await append_flow(rt, db, store)
    res = await run(rt, wid, trigger_data={"name": "Ada"})
    ex = res["execution"]
    assert ex["status"] == "waiting" and ex["resume_at"] is None and not route.called
    (pending,) = res["pending_approvals"]
    assert pending["node_name"] == "Append" and pending["risk"] == "write" and pending["args"]["values"] == ["Ada", "x"]
    assert await drain(rt) == 0                                  # nothing to claim while waiting

    decided = await rt.executions.decide_approval(USER_A, pending["approval_id"], True)
    assert decided["status"] == "queued"
    with pytest.raises(ExecutionError) as e:
        await rt.executions.decide_approval(USER_A, pending["approval_id"], True)       # double submit
    assert e.value.status == 409
    await drain(rt)
    res = await rt.executions.get(USER_A, ex["id"])
    assert res["execution"]["status"] == "success" and route.call_count == 1
    assert statuses(res)["Append"] == "success"


@respx.mock
async def test_rejected_approval_fails_the_node_and_does_not_call_the_app(rt, db, store):
    route = respx.post(url__regex=r".*/values/.*:append").respond(json={})
    wid = await append_flow(rt, db, store)
    res = await run(rt, wid, trigger_data={"name": "Ada"})
    await rt.executions.decide_approval(USER_A, res["pending_approvals"][0]["approval_id"], False)
    await drain(rt)
    res = await rt.executions.get(USER_A, res["execution"]["id"])
    assert res["execution"]["status"] == "error" and res["execution"]["error"]["kind"] == "declined"
    assert not route.called


@respx.mock
@pytest.mark.parametrize("mode,runs", [("off", False), ("writes", True), ("all", True)])
async def test_auto_approve_modes_for_write_nodes(rt, db, store, mode, runs):
    route = respx.post(url__regex=r".*/values/.*:append").respond(json={})
    wid = await append_flow(rt, db, store, settings={"auto_approve": mode})
    res = await run(rt, wid, trigger_data={"name": "Ada"})
    assert (res["execution"]["status"] == "success") is runs and route.called is runs


async def test_destructive_nodes_pause_unless_auto_approve_is_all(rt, db, store, monkeypatch):
    from app.workflows.registry import get_registry

    monkeypatch.setattr(get_registry().get("google_sheets__append_row"), "risk", "destructive")
    route = respx.mock(assert_all_called=False)
    with route:
        route.post(url__regex=r".*/values/.*:append").respond(json={})
        w1 = await append_flow(rt, db, store, settings={"auto_approve": "writes"})
        assert (await run(rt, w1, trigger_data={"name": "A"}))["execution"]["status"] == "waiting"
        w2 = await append_flow(rt, db, store, settings={"auto_approve": "all"}, label="second")
        assert (await run(rt, w2, trigger_data={"name": "A"}))["execution"]["status"] == "success"


@respx.mock
async def test_http_post_is_a_write_and_needs_approval(rt):
    route = respx.post("https://api.example.com/in").respond(200, json={"ok": 1})
    wid = await make(rt, TRIG, n("h", "http_request", "Post", {"method": "POST", "url": "https://api.example.com/in"}),
                     c("t", "h"))
    res = await run(rt, wid)
    assert res["execution"]["status"] == "waiting" and res["pending_approvals"][0]["risk"] == "write"
    assert not route.called


@respx.mock
async def test_approvals_are_private_and_expire(rt, db, store):
    wid = await append_flow(rt, db, store)
    res = await run(rt, wid, trigger_data={"name": "Ada"})
    aid = res["pending_approvals"][0]["approval_id"]
    with pytest.raises(ExecutionError) as e:
        await rt.executions.decide_approval(USER_B, aid, True)
    assert e.value.status == 404
    assert await rt.executions.pending_approvals(USER_B) == [] and len(await rt.executions.pending_approvals(USER_A)) == 1

    old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    await db.update("execution_approvals", {"id": aid}, {"created_at": old})
    with pytest.raises(ExecutionError) as e:
        await rt.executions.decide_approval(USER_A, aid, True)
    assert e.value.status == 410
    res = await rt.executions.get(USER_A, res["execution"]["id"])
    assert res["execution"]["status"] == "error" and "expired" in res["execution"]["error"]["message"]


@respx.mock
async def test_stale_approvals_are_swept(rt, db, store):
    wid = await append_flow(rt, db, store)
    res = await run(rt, wid, trigger_data={"name": "Ada"})
    old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    await db.update("execution_approvals", {"execution_id": res["execution"]["id"]}, {"created_at": old})
    assert await rt.executions.expire_stale_approvals() == 1
    assert (await rt.executions.get(USER_A, res["execution"]["id"]))["execution"]["status"] == "error"


# ------------------------------------------------------------------ Wait, cancel, queue

async def test_wait_node_pauses_and_resumes_when_due(rt, db):
    wid = await make(rt, TRIG, n("w", "wait", "Pause", {"amount": 30, "unit": "minutes"}),
                     n("s", "set", "After", {"fields": [{"name": "x", "value": 1}]}), c("t", "w"), c("w", "s"))
    row = await rt.executions.start(USER_A, wid, trigger_data={"a": 1})
    await drain(rt)
    ex = (await rt.executions.get(USER_A, row["id"]))["execution"]
    assert ex["status"] == "waiting" and ex["resume_at"]
    assert await drain(rt) == 0                                   # not due yet
    await db.update("executions", {"id": row["id"]}, {"resume_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()})
    await drain(rt)
    res = await rt.executions.get(USER_A, row["id"])
    assert res["execution"]["status"] == "success" and out(res, "After") == [{"a": 1, "x": 1}]
    assert out(res, "Pause") == [{"a": 1}]                        # passed straight through on resume


async def test_wait_in_the_past_does_not_pause(rt):
    wid = await make(rt, TRIG, n("w", "wait", "Pause", {"mode": "time", "resume_at": "2000-01-01T00:00:00Z"}),
                     c("t", "w"))
    assert (await run(rt, wid))["execution"]["status"] == "success"


async def test_cancel_a_queued_run(rt):
    wid = await make(rt, TRIG)
    row = await rt.executions.start(USER_A, wid)
    assert (await rt.executions.cancel(USER_A, row["id"]))["status"] == "canceled"
    assert await drain(rt) == 0
    with pytest.raises(ExecutionError) as e:
        await rt.executions.cancel(USER_A, row["id"])
    assert e.value.status == 409
    with pytest.raises(ExecutionError) as e:
        await rt.executions.cancel(USER_B, row["id"])
    assert e.value.status == 404


async def test_cancel_mid_run_stops_after_the_current_node(rt, db, monkeypatch):
    real = handlers.HANDLERS["set"]

    async def cancel_then_run(ctx):
        await db.update("executions", {"id": ctx.run.row["id"]}, {"status": "canceled"})
        return await real(ctx)

    monkeypatch.setitem(handlers.HANDLERS, "set", cancel_then_run)
    wid = await make(rt, TRIG, n("a", "set", "A"), n("b", "set", "B"), c("t", "a"), c("a", "b"))
    res = await run(rt, wid)
    assert res["execution"]["status"] == "canceled" and "B" not in statuses(res)


async def test_queue_claims_each_job_once_and_reclaims_dead_workers(rt, db):
    wid = await make(rt, TRIG)
    row = await rt.executions.start(USER_A, wid)
    first = await db.rpc("claim_next_execution", {"p_worker": "a", "p_lease_seconds": 300})
    assert first[0]["id"] == row["id"] and first[0]["status"] == "running"
    assert await db.rpc("claim_next_execution", {"p_worker": "b", "p_lease_seconds": 300}) == []   # taken
    stale = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    await db.update("executions", {"id": row["id"]}, {"locked_at": stale})
    again = await db.rpc("claim_next_execution", {"p_worker": "b", "p_lease_seconds": 300})
    assert again[0]["locked_by"] == "b"                                                           # dead worker's job


async def test_unattended_modes_need_a_published_workflow(rt):
    wid = await make(rt, n("w", "webhook_trigger", "Hook"))
    with pytest.raises(ExecutionError) as e:
        await rt.executions.start(USER_A, wid, mode="webhook", trigger_node_id="w")
    assert e.value.status == 409 and "Publish" in e.value.message


async def test_pinned_data_replaces_a_node_in_manual_runs(rt, monkeypatch):
    called = []

    async def spy(ctx):
        called.append(1)
        raise AssertionError("must not run a pinned node")

    monkeypatch.setitem(handlers.HANDLERS, "http_request", spy)
    wid = await make(rt, TRIG, n("h", "http_request", "Fetch", {"url": "https://api.example.com/x"},
                                 pinned_data=[{"json": {"fake": 1}}]),
                     n("s", "set", "Use", {"fields": [{"name": "got", "value": "{{ $json.fake }}"}]}), c("t", "h"), c("h", "s"))
    res = await run(rt, wid)
    assert not called and statuses(res)["Fetch"] == "pinned" and out(res, "Use") == [{"fake": 1, "got": 1}]


# ------------------------------------------------------------------ run from here and test node

@respx.mock
async def test_run_from_here_reuses_upstream_data_and_skips_it(rt):
    first = respx.get("https://api.example.com/a").respond(200, json={"v": 1})
    wid = await make(rt, TRIG, n("h", "http_request", "Fetch", {"url": "https://api.example.com/a"}),
                     n("s", "set", "Shape", {"fields": [{"name": "double", "value": "{{ $json.v * 2 }}", "type": "number"}]}),
                     n("l", "limit", "Last", {"max_items": 5}), c("t", "h"), c("h", "s"), c("s", "l"))
    res = await run(rt, wid)
    assert out(res, "Last") == [{"v": 1, "double": 2}] and first.call_count == 1

    # Change the Set node and re-run only from it: Fetch must not be called again.
    doc = await rt.workflows.get(USER_A, wid)
    await rt.workflows.patch(USER_A, wid, doc["version"], [{"op": "update_node", "id": "s", "parameters": {
        "fields": [{"name": "double", "value": "{{ $json.v * 10 }}", "type": "number"}]}}])
    res2 = await run(rt, wid, start_node_id="s")
    assert first.call_count == 1 and "Fetch" not in statuses(res2) and "Start" not in statuses(res2)
    assert out(res2, "Last") == [{"v": 1, "double": 10}]


async def test_run_from_here_without_saved_data_explains_what_to_do(rt):
    wid = await make(rt, TRIG, n("s", "set", "Shape"), c("t", "s"))
    with pytest.raises(ExecutionError) as e:
        await rt.executions.start(USER_A, wid, start_node_id="s")
    assert e.value.status == 422 and "'Start'" in e.value.message and "pin" in e.value.message


async def test_run_from_here_can_use_pinned_data(rt):
    wid = await make(rt, n("t", "manual_trigger", "Start", pinned_data=[{"json": {"v": 4}}]),
                     n("s", "set", "Shape", {"fields": [{"name": "w", "value": "{{ $json.v + 1 }}"}]}), c("t", "s"))
    res = await run(rt, wid, start_node_id="s")
    assert out(res, "Shape") == [{"v": 4, "w": 5}]


@respx.mock
async def test_test_node_runs_one_node_with_upstream_data_and_nothing_downstream(rt):
    wid = await make(rt, n("t", "manual_trigger", "Start", pinned_data=[{"json": {"name": "Ada"}}]),
                     n("s", "set", "Hello", {"fields": [{"name": "msg", "value": "hi {{ $json.name }}"}]}),
                     n("d", "set", "Downstream", {}), c("t", "s"), c("s", "d"))
    res = await rt.executions.test_node(USER_A, wid, "s")
    assert res["status"] == "success" and res["output"]["main"][0]["json"] == {"name": "Ada", "msg": "hi Ada"}
    rows = [r["node_name"] for r in db_rows(rt, "node_executions")]
    assert "Downstream" not in rows
    res = await rt.executions.test_node(USER_A, wid, "s", input_items=[{"json": {"name": "Bob"}}])
    assert res["output"]["main"][0]["json"]["msg"] == "hi Bob"


def db_rows(rt, table):
    return rt.workflows.db.tables.get(table, [])


@respx.mock
async def test_test_node_on_a_write_node_requires_confirmation(rt, db, store):
    route = respx.post(url__regex=r".*/values/.*:append").respond(json={})
    conn = await connect(db, store, "google_sheets")
    wid = await make(rt, n("t", "manual_trigger", "Start", pinned_data=[{"json": {"name": "Ada"}}]),
                     n("g", "google_sheets__append_row", "Append", APPEND, connection_id=conn["id"]), c("t", "g"))
    with pytest.raises(ExecutionError) as e:
        await rt.executions.test_node(USER_A, wid, "g")
    assert e.value.status == 409 and e.value.extra["requires_confirmation"] is True and not route.called
    res = await rt.executions.test_node(USER_A, wid, "g", confirm=True)
    assert res["status"] == "success" and route.call_count == 1


async def test_test_node_reports_node_errors_and_missing_data(rt):
    wid = await make(rt, TRIG, n("e", "stop_and_error", "Halt", {"message": "x"}), c("t", "e"))
    with pytest.raises(ExecutionError) as e:
        await rt.executions.test_node(USER_A, wid, "e")
    assert e.value.status == 422 and "no saved data" in e.value.message
    res = await rt.executions.test_node(USER_A, wid, "e", input_items=[{"json": {}}])
    assert res["status"] == "error" and res["error"]["message"] == "x"


# ------------------------------------------------------------------ error workflow

async def test_error_workflow_runs_for_unattended_failures_only(rt):
    handler_wf = await make(rt, n("et", "error_trigger", "OnError"),
                            n("s", "set", "Note", {"fields": [{"name": "msg", "value": "{{ $json.workflow.name }}: {{ $json.execution.error.message }}"}]}),
                            c("et", "s"), name="Handler")
    main = await make(rt, n("w", "webhook_trigger", "Hook"), n("e", "stop_and_error", "Halt", {"message": "kaboom"}),
                      c("w", "e"), name="Main", settings={"error_workflow_id": handler_wf})
    await rt.workflows.publish(USER_A, main)

    # A manual run failing does not trigger the error workflow.
    await run(rt, main, trigger_node_id="w")
    assert await rt.executions.list(USER_A, handler_wf) == []

    row = await rt.executions.start(USER_A, main, mode="webhook", trigger_node_id="w", trigger_data={"x": 1})
    await drain(rt)
    assert (await rt.executions.get(USER_A, row["id"]))["execution"]["status"] == "error"
    (err_run,) = await rt.executions.list(USER_A, handler_wf)
    assert err_run["mode"] == "error" and err_run["status"] == "success"
    res = await rt.executions.get(USER_A, err_run["id"])
    assert out(res, "Note") == [{"execution": {"id": row["id"], "error": {"message": "kaboom"}, "lastNodeExecuted": "Halt",
                                              "mode": "webhook"}, "workflow": {"id": main, "name": "Main"},
                                 "msg": "Main: kaboom"}]


# ------------------------------------------------------------------ HTTP API

@respx.mock
async def test_http_endpoints_run_approve_and_read(make_client, db, store, rt):
    route = respx.post(url__regex=r".*/values/.*:append").respond(json={})
    c_ = make_client(None)
    conn = await connect(db, store, "google_sheets")
    wf = c_.post("/api/workflows", headers=auth(), json={"name": "API", "operations": [
        n("t", "manual_trigger", "Start"), n("g", "google_sheets__append_row", "Append", APPEND, connection_id=conn["id"]),
        c("t", "g")]}).json()["workflow"]
    r = c_.post(f"/api/workflows/{wf['id']}/run", headers=auth(), json={"trigger_data": {"name": "Ada"}})
    assert r.status_code == 202 and r.json()["execution"]["status"] == "queued" and "state" not in r.json()["execution"]
    eid = r.json()["execution"]["id"]
    await rt.executions.process_one("w")            # the worker lives in its own process; drive it here
    got = c_.get(f"/api/executions/{eid}", headers=auth()).json()
    assert got["execution"]["status"] == "waiting" and got["pending_approvals"][0]["node_name"] == "Append"
    assert c_.get("/api/execution-approvals", headers=auth()).json()[0]["approval_id"]
    assert c_.get("/api/execution-approvals", headers=auth(USER_B)).json() == []
    aid = got["pending_approvals"][0]["approval_id"]
    assert c_.post(f"/api/execution-approvals/{aid}/decision", headers=auth(USER_B), json={"approve": True}).status_code == 404
    assert c_.post(f"/api/execution-approvals/{aid}/decision", headers=auth(), json={"approve": True}).json()["status"] == "queued"
    assert c_.post(f"/api/execution-approvals/{aid}/decision", headers=auth(), json={"approve": True}).status_code == 409

    assert [e["id"] for e in c_.get(f"/api/executions?workflow_id={wf['id']}", headers=auth()).json()] == [eid]
    assert c_.get(f"/api/executions/{eid}", headers=auth(USER_B)).status_code == 404
    assert c_.get("/api/executions").status_code == 401

    t = c_.post(f"/api/workflows/{wf['id']}/nodes/g/test", headers=auth(), json={"input": [{"json": {"name": "B"}}]})
    assert t.status_code == 409 and t.json()["detail"]["requires_confirmation"] is True
    t = c_.post(f"/api/workflows/{wf['id']}/nodes/g/test", headers=auth(),
                json={"input": [{"json": {"name": "B"}}], "confirm": True})
    assert t.status_code == 200 and t.json()["status"] == "success" and route.call_count == 1
    assert c_.post(f"/api/workflows/{wf['id']}/run", headers=auth(USER_B), json={}).status_code == 404
