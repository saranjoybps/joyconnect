"""Step 3: schedule computation, trigger registration on publish, the scheduler, and public webhooks."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.workflows import triggers as triggers_mod
from app.workflows.schedule import ScheduleError, compute_next, validate_config
from tests.conftest import USER_A, USER_B
from tests.test_agent import make_client  # noqa: F401
from tests.test_engine import TRIG, c, drain, n, rt  # noqa: F401  (rt fixture)
from tests.test_engine import make as make_wf

UTC = timezone.utc


def at(*a, tz=UTC):
    return datetime(*a, tzinfo=tz)


def cfg(rule, tz="UTC"):
    return {"timezone": tz, "rules": [rule]}


# ------------------------------------------------------------------ schedule computation

def test_seconds_and_minutes_intervals():
    t = at(2026, 1, 1, 10, 0, 0)
    assert compute_next(cfg({"interval": "seconds", "every": 30}), t) == t + timedelta(seconds=30)
    assert compute_next(cfg({"interval": "minutes", "every": 5}), t) == t + timedelta(minutes=5)


def test_minimum_interval_is_enforced():
    assert validate_config(cfg({"interval": "seconds", "every": 5}))
    assert not validate_config(cfg({"interval": "seconds", "every": 10}))


def test_hours_are_calendar_aligned():
    t = at(2026, 1, 1, 10, 20)
    assert compute_next(cfg({"interval": "hours", "every": 1, "minute": 15}), t) == at(2026, 1, 1, 11, 15)
    assert compute_next(cfg({"interval": "hours", "every": 6, "minute": 0}), t) == at(2026, 1, 1, 12, 0)


def test_daily_in_a_time_zone_and_across_dst():
    rule = {"interval": "days", "every": 1, "hour": 9, "minute": 0}
    paris = ZoneInfo("Europe/Paris")
    # Winter: Paris is UTC+1.
    assert compute_next(cfg(rule, "Europe/Paris"), at(2026, 3, 1, 12)) == at(2026, 3, 2, 9, tz=paris)
    assert compute_next(cfg(rule, "Europe/Paris"), at(2026, 3, 1, 12)).utcoffset() is not None
    # Day after the spring-forward (29 March 2026): 09:00 Paris is 07:00 UTC, not 08:00.
    nxt = compute_next(cfg(rule, "Europe/Paris"), at(2026, 3, 29, 12))
    assert nxt.astimezone(UTC) == at(2026, 3, 30, 7)


def test_weekly_on_chosen_days():
    rule = {"interval": "weeks", "every": 1, "weekdays": [1, 3], "hour": 8, "minute": 30}   # Mon, Wed
    assert compute_next(cfg(rule), at(2026, 1, 1, 0)) == at(2026, 1, 5, 8, 30)   # Thursday 1 Jan -> Monday
    assert compute_next(cfg(rule), at(2026, 1, 5, 9)) == at(2026, 1, 7, 8, 30)


def test_monthly():
    rule = {"interval": "months", "every": 1, "day_of_month": 15, "hour": 12, "minute": 0}
    assert compute_next(cfg(rule), at(2026, 1, 20)) == at(2026, 2, 15, 12)


def test_cron_expressions():
    assert compute_next(cfg({"interval": "cron", "expression": "*/15 * * * *"}), at(2026, 1, 1, 10, 7)) == at(2026, 1, 1, 10, 15)
    assert compute_next(cfg({"interval": "cron", "expression": "0 9 * * 1-5"}), at(2026, 1, 2, 10)) == at(2026, 1, 5, 9)   # Fri -> Mon
    assert compute_next(cfg({"interval": "cron", "expression": "30 8 1 * *"}), at(2026, 1, 2)) == at(2026, 2, 1, 8, 30)


def test_invalid_schedules_are_reported():
    assert validate_config({"rules": []})
    assert validate_config(cfg({"interval": "cron", "expression": "nope"}))
    assert validate_config(cfg({"interval": "days"}, "Mars/Phobos"))
    assert validate_config(cfg({"interval": "weeks", "weekdays": [9]}))
    assert validate_config(cfg({"interval": "fortnights"}))
    assert not validate_config(cfg({"interval": "days", "every": 1, "hour": 3}))


# ------------------------------------------------------------------ registration on publish

SCHED = {"rules": [{"interval": "minutes", "every": 1}]}


async def schedule_wf(rt, params=None, name="Sched"):
    wid = await make_wf(rt, n("sch", "schedule_trigger", "Every", params or SCHED),
                        n("s", "set", "Mark", {"fields": [{"name": "ts", "value": "{{ $json.timestamp }}"}]}),
                        c("sch", "s"), name=name)
    return wid


async def test_publish_registers_schedule_and_unpublish_deactivates(rt, db):
    wid = await schedule_wf(rt)
    assert await db.select("triggers", {"workflow_id": wid}) == []          # drafts register nothing
    await rt.workflows.publish(USER_A, wid)
    (t,) = await db.select("triggers", {"workflow_id": wid})
    assert t["type"] == "schedule" and t["active"] and t["next_run_at"]
    await rt.workflows.unpublish(USER_A, wid)
    assert not (await db.select("triggers", {"workflow_id": wid}))[0]["active"]


async def test_publish_rejects_a_bad_schedule(rt):
    wid = await schedule_wf(rt, {"rules": [{"interval": "cron", "expression": "bad"}]})
    from app.workflows.service import WorkflowError

    with pytest.raises(WorkflowError) as e:
        await rt.workflows.publish(USER_A, wid)
    assert "cron" in e.value.message.lower()


async def test_republish_removes_triggers_of_deleted_nodes(rt, db):
    wid = await schedule_wf(rt)
    await rt.workflows.publish(USER_A, wid)
    doc = await rt.workflows.get(USER_A, wid)
    await rt.workflows.patch(USER_A, wid, doc["version"], [
        {"op": "add_node", "node": {"id": "m", "type": "manual_trigger", "name": "M", "parameters": {}}},
        {"op": "remove_node", "id": "sch"}])
    await rt.workflows.publish(USER_A, wid)
    assert await db.select("triggers", {"workflow_id": wid}) == []


# ------------------------------------------------------------------ the scheduler

async def test_due_schedule_fires_once_and_runs_the_published_snapshot(rt, db):
    wid = await schedule_wf(rt)
    await rt.workflows.publish(USER_A, wid)
    (t,) = await db.select("triggers", {"workflow_id": wid})
    assert await rt.triggers.fire_due_schedules() == 0                       # not due yet
    await db.update("triggers", {"id": t["id"]}, {"next_run_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()})
    assert await rt.triggers.fire_due_schedules() == 1
    assert await rt.triggers.fire_due_schedules() == 0                       # next_run_at moved forward
    await drain(rt)
    (ex,) = await db.select("executions", {"workflow_id": wid})
    assert ex["mode"] == "schedule" and ex["status"] == "success"
    (t,) = await db.select("triggers", {"workflow_id": wid})
    assert datetime.fromisoformat(t["next_run_at"]) > datetime.now(UTC) and t["last_run_at"]


async def test_two_schedulers_never_double_fire(rt, db):
    import asyncio

    wid = await schedule_wf(rt)
    await rt.workflows.publish(USER_A, wid)
    (t,) = await db.select("triggers", {"workflow_id": wid})
    await db.update("triggers", {"id": t["id"]}, {"next_run_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat()})
    fired = await asyncio.gather(*[rt.triggers.fire_due_schedules() for _ in range(5)])
    assert sum(fired) == 1
    assert len(await db.select("executions", {"workflow_id": wid})) == 1


async def test_missed_runs_are_discarded_not_replayed(rt, db):
    wid = await schedule_wf(rt)
    await rt.workflows.publish(USER_A, wid)
    (t,) = await db.select("triggers", {"workflow_id": wid})
    await db.update("triggers", {"id": t["id"]}, {"next_run_at": (datetime.now(UTC) - timedelta(days=3)).isoformat()})
    assert await rt.triggers.fire_due_schedules() == 1
    assert await rt.triggers.fire_due_schedules() == 0


async def test_unpublished_workflow_does_not_fire(rt, db):
    wid = await schedule_wf(rt)
    await rt.workflows.publish(USER_A, wid)
    (t,) = await db.select("triggers", {"workflow_id": wid})
    await db.update("triggers", {"id": t["id"]}, {"next_run_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()})
    await rt.workflows.unpublish(USER_A, wid)
    assert await rt.triggers.fire_due_schedules() == 0
    assert await db.select("executions", {"workflow_id": wid}) == []


async def test_manual_run_works_on_a_draft_but_unattended_needs_publishing(rt):
    wid = await schedule_wf(rt)
    ex = await rt.executions.start(USER_A, wid, trigger_node_id="sch", trigger_data={"timestamp": "x"})
    assert ex["mode"] == "manual"
    from app.workflows.runner import ExecutionError

    with pytest.raises(ExecutionError):
        await rt.executions.start(USER_A, wid, mode="schedule", trigger_node_id="sch", trigger_data={})


# ------------------------------------------------------------------ webhooks

def hook_params(**kw):
    return {"http_method": "POST", "authentication": "none", "response_mode": "immediately", **kw}


async def hook_wf(rt, params=None, extra=(), name="Hook"):
    wid = await make_wf(rt, n("w", "webhook_trigger", "In", params or hook_params()),
                        n("s", "set", "Echo", {"fields": [{"name": "who", "value": "{{ $json.body.name }}"}]}),
                        c("w", "s"), *extra, name=name)
    doc, extras = await rt.workflows.publish(USER_A, wid)
    return wid, extras


async def test_publish_returns_secret_once_and_never_stores_it_in_the_workflow(rt, db):
    wid, extras = await hook_wf(rt, hook_params(authentication="header"))
    secret = extras["webhook_secrets"]["w"]
    assert len(secret) >= 32
    assert secret not in str(await db.select("workflows", {"id": wid}))
    assert secret not in str(await db.select("workflow_versions", {"workflow_id": wid}))
    assert secret not in str(await db.select("triggers", {"workflow_id": wid}))
    items = await rt.triggers.list(USER_A, wid)
    assert items[0]["has_secret"] and secret not in str(items) and items[0]["url"].endswith(
        (await db.select("triggers", {"workflow_id": wid}))[0]["path"])


async def test_webhook_starts_the_published_workflow(make_client, rt, db):
    wid, _ = await hook_wf(rt)
    (t,) = await db.select("triggers", {"workflow_id": wid})
    client = make_client(None)
    r = client.post(f"/api/hooks/{t['path']}?a=1", json={"name": "Ada"}, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 200 and r.json() == {"message": "Workflow was started"}
    await drain(rt)
    (ex,) = await db.select("executions", {"workflow_id": wid})
    assert ex["mode"] == "webhook" and ex["status"] == "success"
    (node,) = [x for x in await db.select("node_executions", {"execution_id": ex["id"]}) if x["node_name"] == "In"]
    item = node["output"]["main"][0]["json"]
    assert item["body"] == {"name": "Ada"} and item["query"] == {"a": "1"} and item["headers"]["content-type"]
    assert "authorization" not in item["headers"]


async def test_unknown_path_and_unpublished_workflows_are_404(make_client, rt, db):
    wid, _ = await hook_wf(rt)
    (t,) = await db.select("triggers", {"workflow_id": wid})
    client = make_client(None)
    assert client.post("/api/hooks/does-not-exist", json={}).status_code == 404
    await rt.workflows.unpublish(USER_A, wid)
    assert client.post(f"/api/hooks/{t['path']}", json={}).status_code == 404


async def test_wrong_method_is_405(make_client, rt, db):
    wid, _ = await hook_wf(rt)
    (t,) = await db.select("triggers", {"workflow_id": wid})
    r = make_client(None).get(f"/api/hooks/{t['path']}")
    assert r.status_code == 405 and r.headers["allow"] == "POST"


async def test_header_authentication(make_client, rt, db):
    wid, extras = await hook_wf(rt, hook_params(authentication="header", header_name="X-Key"))
    secret = extras["webhook_secrets"]["w"]
    (t,) = await db.select("triggers", {"workflow_id": wid})
    client = make_client(None)
    url = f"/api/hooks/{t['path']}"
    assert client.post(url, json={}).status_code == 401
    assert client.post(url, json={}, headers={"X-Key": "wrong"}).status_code == 401
    assert client.post(url, json={}, headers={"X-Key": secret}).status_code == 200
    assert len(await db.select("executions", {"workflow_id": wid})) == 1      # rejected calls started nothing


async def test_rotating_the_secret_invalidates_the_old_one(make_client, rt, db):
    wid, extras = await hook_wf(rt, hook_params(authentication="header"))
    old = extras["webhook_secrets"]["w"]
    new = await rt.triggers.rotate_secret(USER_A, wid, "w")
    (t,) = await db.select("triggers", {"workflow_id": wid})
    client = make_client(None)
    assert client.post(f"/api/hooks/{t['path']}", json={}, headers={"X-Webhook-Secret": old}).status_code == 401
    assert client.post(f"/api/hooks/{t['path']}", json={}, headers={"X-Webhook-Secret": new}).status_code == 200


async def test_republish_keeps_the_same_url_and_secret(rt, db):
    wid, extras = await hook_wf(rt, hook_params(authentication="header"))
    (before,) = await db.select("triggers", {"workflow_id": wid})
    doc = await rt.workflows.get(USER_A, wid)
    await rt.workflows.patch(USER_A, wid, doc["version"], [{"op": "move", "id": "s", "position": {"x": 5, "y": 5}}])
    _, again = await rt.workflows.publish(USER_A, wid)
    (after,) = await db.select("triggers", {"workflow_id": wid})
    assert after["path"] == before["path"] and after["secret_id"] == before["secret_id"]
    assert again["webhook_secrets"] == {}


async def test_body_size_limit_and_bad_json(make_client, rt, db, settings):
    wid, _ = await hook_wf(rt)
    (t,) = await db.select("triggers", {"workflow_id": wid})
    client = make_client(None)
    url = f"/api/hooks/{t['path']}"
    big = b"x" * (settings.webhook_max_body_bytes + 1)
    assert client.post(url, content=big, headers={"Content-Type": "text/plain"}).status_code == 413
    assert client.post(url, content=b"{bad", headers={"Content-Type": "application/json"}).status_code == 400
    assert client.post(url, data={"a": "1"}).status_code == 200                # form bodies are parsed too


async def test_rate_limit_per_path(make_client, rt, db, settings):
    wid, _ = await hook_wf(rt)
    (t,) = await db.select("triggers", {"workflow_id": wid})
    client = make_client(None)
    codes = [client.post(f"/api/hooks/{t['path']}", json={}).status_code
             for _ in range(settings.webhook_rate_limit_per_minute + 3)]
    assert codes[:settings.webhook_rate_limit_per_minute] == [200] * settings.webhook_rate_limit_per_minute
    assert set(codes[settings.webhook_rate_limit_per_minute:]) == {429}


async def test_response_modes_last_node_and_respond_node(make_client, rt, db, monkeypatch):
    async def work(_):
        await drain(rt)

    monkeypatch.setattr(triggers_mod, "_sleep", work)
    client = make_client(None)

    wid, _ = await hook_wf(rt, hook_params(response_mode="respond_node", response_code=201), extra=(), name="R1")
    doc = await rt.workflows.get(USER_A, wid)
    await rt.workflows.patch(USER_A, wid, doc["version"], [
        {"op": "add_node", "node": {"id": "r", "type": "respond_to_webhook", "name": "Reply",
                                    "parameters": {"respond_with": "json", "response_code": 202,
                                                   "body": {"ok": True, "who": "{{ $json.who }}"},
                                                   "headers": {"X-Thing": "1", "Set-Cookie": "a=b"}}}},
        {"op": "connect", "from": "s", "to": "r", "output": "main"}])
    await rt.workflows.publish(USER_A, wid)
    (t,) = await db.select("triggers", {"workflow_id": wid})
    r = client.post(f"/api/hooks/{t['path']}", json={"name": "Ada"})
    assert r.status_code == 202 and r.json() == {"ok": True, "who": "Ada"}
    assert r.headers["x-thing"] == "1" and "set-cookie" not in r.headers      # cookies are never set from a workflow

    wid2, _ = await hook_wf(rt, hook_params(response_mode="last_node"), name="R2")
    (t2,) = [x for x in await db.select("triggers", {"workflow_id": wid2})]
    r = client.post(f"/api/hooks/{t2['path']}", json={"name": "Bob"})
    body = r.json()
    assert r.status_code == 200 and (body[0] if isinstance(body, list) else body)["who"] == "Bob"


async def test_failed_run_in_response_mode_is_a_500_without_details(make_client, rt, db, monkeypatch):
    async def work(_):
        await drain(rt)

    monkeypatch.setattr(triggers_mod, "_sleep", work)
    wid = await make_wf(rt, n("w", "webhook_trigger", "In", hook_params(response_mode="last_node")),
                        n("e", "stop_and_error", "Halt", {"message": "secret internal detail"}), c("w", "e"))
    await rt.workflows.publish(USER_A, wid)
    (t,) = await db.select("triggers", {"workflow_id": wid})
    r = make_client(None).post(f"/api/hooks/{t['path']}", json={})
    assert r.status_code == 500 and "secret internal detail" not in r.text


async def test_triggers_listing_is_private_to_the_owner(rt):
    wid, _ = await hook_wf(rt)
    from app.workflows.service import WorkflowError

    with pytest.raises(WorkflowError):
        await rt.triggers.list(USER_B, wid)
    with pytest.raises(WorkflowError):
        await rt.triggers.rotate_secret(USER_B, wid, "w")
