"""Run history API: listing, filters, redaction, isolation between users."""

import respx

from app.agent.llm import LLMResult
from tests.conftest import USER_A, USER_B, auth
from tests.test_agent import FakeLLM, call, connect, events, make_client  # noqa: F401  (fixture)


@respx.mock
async def test_runs_list_filters_and_redaction(make_client, db, store):
    await connect(db, store, "stripe")
    await connect(db, store, "slack")
    respx.get("https://api.stripe.com/v1/balance").respond(json={"livemode": False, "available": [], "pending": []})
    respx.post("https://slack.com/api/conversations.list").respond(json={"ok": False, "error": "invalid_auth"})
    client = make_client(FakeLLM(
        call("stripe__get_balance", {}, id="a"), call("slack__list_channels", {}, id="b"), LLMResult(content="done")))
    events(client.post("/api/chat", json={"message": "go"}, headers=auth()))

    body = client.get("/api/runs", headers=auth()).json()
    assert body["total"] == 2
    by_tool = {r["tool"]: r for r in body["runs"]}
    stripe, slack = by_tool["stripe__get_balance"], by_tool["slack__list_channels"]
    assert (stripe["connector"], stripe["connector_name"], stripe["risk"], stripe["status"]) == (
        "stripe", "Stripe", "read", "ok")
    assert isinstance(stripe["duration_ms"], int) and stripe["input"] == {} and "available" in stripe["output"]
    assert slack["status"] == "error" and "Reconnect Slack" in slack["output"]["error"]

    only = client.get("/api/runs", params={"connector": "stripe"}, headers=auth()).json()
    assert [r["tool"] for r in only["runs"]] == ["stripe__get_balance"] and only["total"] == 1
    errors = client.get("/api/runs", params={"status": "error"}, headers=auth()).json()
    assert [r["tool"] for r in errors["runs"]] == ["slack__list_channels"]
    both = client.get("/api/runs", params={"status": "error", "connector": "stripe"}, headers=auth()).json()
    assert both["runs"] == []
    assert any(c["id"] == "airtable" for c in body["connectors"]) and "ok" in body["statuses"]


async def test_runs_are_private_paged_and_need_login(make_client, db):
    client = make_client(FakeLLM())
    for i in range(5):
        await db.insert("tool_runs", {"user_id": USER_A, "tool": "stripe__get_balance", "status": "ok",
                                      "args_redacted": {"api_key": "[REDACTED]"}, "result_summary": f"r{i}"})
    await db.insert("tool_runs", {"user_id": USER_B, "tool": "slack__list_channels", "status": "ok"})
    page = client.get("/api/runs", params={"limit": 2, "offset": 1}, headers=auth()).json()
    assert page["total"] == 5 and len(page["runs"]) == 2
    old = page["runs"][0]                    # rows written before the history columns existed still render
    assert old["connector"] == "stripe" and old["risk"] == "read" and old["output"].startswith("r")
    assert client.get("/api/runs", headers=auth(USER_B)).json()["total"] == 1
    assert client.get("/api/runs").status_code == 401
    assert client.get("/api/runs", params={"limit": 999}, headers=auth()).status_code == 422
