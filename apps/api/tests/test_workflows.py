"""Step 1: workflow schema, node registry, patch API, versioning and conflicts."""

import json

import pytest

from app.connectors.registry import all_tools
from app.workflows.patch import PatchError, apply_operations, parse_operations, patch_risk
from app.workflows.registry import get_registry
from app.workflows.schema import publish_errors, schema_errors, structural_errors
from tests.conftest import USER_A, USER_B, auth
from tests.test_agent import connect, make_client  # noqa: F401


def empty(**over):
    return {"id": "w1", "name": "Test", "status": "draft", "version": 1, "nodes": [], "edges": [], "settings": {},
            **over}


def ops(*raw):
    return parse_operations(list(raw))


def add(nid, type_, name=None, **kw):
    return {"op": "add_node", "node": {"id": nid, "type": type_, "name": name or nid, **kw}}


# ------------------------------------------------------------------ schema and registry

def test_registry_has_core_nodes_and_one_app_node_per_connector_tool():
    reg = get_registry()
    core = {"manual_trigger", "schedule_trigger", "webhook_trigger", "error_trigger", "if", "switch", "merge",
            "loop_over_items", "wait", "filter", "stop_and_error", "execute_sub_workflow", "set", "aggregate",
            "split_out", "sort", "limit", "http_request", "respond_to_webhook"}
    assert core <= {n.type for n in reg.all()}
    app_nodes = {n.type: n for n in reg.all() if n.category == "app"}
    assert set(app_nodes) == set(all_tools())
    node = app_nodes["google_sheets__append_row"]
    assert node.connector == "google_sheets" and node.risk == "write"
    assert node.parameters == all_tools()["google_sheets__append_row"][1].parameters   # from the tool schema


def test_dynamic_outputs_and_risk():
    reg = get_registry()
    assert reg.get("if").output_names() == ["true", "false"]
    assert reg.get("switch").output_names({"rules": [{}, {}, {}]}) == ["case_0", "case_1", "case_2"]
    assert reg.get("switch").output_names({"rules": [{}], "fallback": "extra"}) == ["case_0", "fallback"]
    assert reg.get("switch").output_names({"mode": "expression", "number_of_outputs": 3}) == [
        "case_0", "case_1", "case_2"]
    assert reg.get("http_request").risk_of({"method": "GET"}) == "read"
    assert reg.get("http_request").risk_of({"method": "post"}) == "write"
    assert reg.get("loop_over_items").output_names() == ["loop", "done"]
    assert reg.get("merge").inputs == ["input1", "input2"]


def test_schema_rejects_bad_documents():
    assert schema_errors(empty()) == []
    assert schema_errors({"id": "x"})                                   # missing required fields
    assert schema_errors(empty(status="live"))
    assert schema_errors(empty(extra=1))
    bad_node = {"id": "bad id!", "type": "set", "name": "x", "parameters": {}, "position": {"x": 0, "y": 0}}
    assert any("pattern" in e or "does not match" in e for e in schema_errors(empty(nodes=[bad_node])))


def test_structural_rules():
    n = lambda i, t, name=None: {"id": i, "type": t, "name": name or i, "parameters": {},   # noqa: E731
                                 "position": {"x": 0, "y": 0}}
    doc = empty(nodes=[n("a", "manual_trigger"), n("a", "set")])
    assert any("duplicate node id" in e for e in structural_errors(doc))
    doc = empty(nodes=[n("a", "manual_trigger", "Same"), n("b", "set", "Same")])
    assert any("duplicate node name" in e for e in structural_errors(doc))
    doc = empty(nodes=[n("a", "nope")])
    assert any("unknown node type" in e for e in structural_errors(doc))
    doc = empty(nodes=[n("a", "manual_trigger"), n("b", "if")], edges=[{"from": "a", "to": "b", "output": "yes"}])
    assert any("no output 'yes'" in e for e in structural_errors(doc))
    doc = empty(nodes=[n("a", "set"), n("b", "manual_trigger")], edges=[{"from": "a", "to": "b", "output": "main"}])
    assert any("is a trigger and takes no input" in e for e in structural_errors(doc))
    doc = empty(nodes=[n("a", "manual_trigger"), n("b", "merge")],
                edges=[{"from": "a", "to": "b", "output": "main", "input": "input3"}])
    assert any("no input 'input3'" in e for e in structural_errors(doc))
    doc = empty(nodes=[n("a", "set")], edges=[{"from": "a", "to": "ghost", "output": "main"}])
    assert any("does not exist" in e for e in structural_errors(doc))


# ------------------------------------------------------------------ patch operations

def test_add_connect_rename_move_update_remove():
    doc = empty()
    doc, log = apply_operations(doc, ops(
        add("t", "manual_trigger", "Start"),
        add("s", "set", "Set fields", parameters={"mode": "manual"}),
        {"op": "connect", "from": "t", "to": "s"},
        {"op": "rename", "name": "Renamed"},
        {"op": "rename", "id": "s", "name": "Prepare"},
        {"op": "move", "id": "s", "position": {"x": 10, "y": 20}},
        {"op": "update_node", "id": "Prepare", "parameters": {"keep_only_set": True}},
        {"op": "set_settings", "settings": {"auto_approve": "writes"}},
    ))
    assert doc["name"] == "Renamed" and doc["settings"] == {"auto_approve": "writes"}
    s = next(n for n in doc["nodes"] if n["id"] == "s")
    assert s["name"] == "Prepare" and s["position"] == {"x": 10, "y": 20}
    assert s["parameters"] == {"mode": "manual", "keep_only_set": True}     # merged, not replaced
    assert doc["edges"] == [{"from": "t", "to": "s", "output": "main"}]
    assert [c["op"] for c in log][:2] == ["add_node", "add_node"]

    doc, _ = apply_operations(doc, ops({"op": "update_node", "id": "s", "parameters": {"mode": "json"},
                                        "replace": True}))
    assert next(n for n in doc["nodes"] if n["id"] == "s")["parameters"] == {"mode": "json"}

    doc, _ = apply_operations(doc, ops({"op": "disconnect", "from": "t", "to": "s"}))
    assert doc["edges"] == []
    doc, _ = apply_operations(doc, ops({"op": "connect", "from": "t", "to": "s"}, {"op": "remove_node", "id": "s"}))
    assert [n["id"] for n in doc["nodes"]] == ["t"] and doc["edges"] == []          # edges went with the node


def test_add_node_generates_id_dedupes_names_and_places_to_the_right():
    doc, log = apply_operations(empty(), ops(
        {"op": "add_node", "node": {"type": "manual_trigger"}},
        {"op": "add_node", "node": {"type": "set"}},
        {"op": "add_node", "node": {"type": "set"}}))
    assert [n["name"] for n in doc["nodes"]] == ["Manual Trigger", "Edit Fields (Set)", "Edit Fields (Set) 2"]
    assert len({n["id"] for n in doc["nodes"]}) == 3 and all(n["id"].startswith("n_") for n in doc["nodes"])
    xs = [n["position"]["x"] for n in doc["nodes"]]
    assert xs == sorted(xs) and len(set(xs)) == 3


def test_input_document_is_not_mutated_and_failure_is_atomic():
    doc = empty()
    before = json.dumps(doc)
    with pytest.raises(PatchError) as e:
        apply_operations(doc, ops(add("a", "manual_trigger"), add("b", "does_not_exist")))
    assert "unknown node type" in str(e.value) and e.value.index == 1
    assert json.dumps(doc) == before


@pytest.mark.parametrize("operation,fragment", [
    ({"op": "remove_node", "id": "ghost"}, "no node with id or name 'ghost'"),
    ({"op": "connect", "from": "a", "to": "ghost"}, "no node with id or name"),
    ({"op": "disconnect", "from": "a", "to": "b"}, "is not connected"),
    ({"op": "move", "id": "ghost", "position": {"x": 0, "y": 0}}, "no node"),
])
def test_patch_errors_name_the_operation(operation, fragment):
    doc, _ = apply_operations(empty(), ops(add("a", "manual_trigger"), add("b", "set")))
    with pytest.raises(PatchError) as e:
        apply_operations(doc, ops(operation))
    assert fragment in str(e.value) and e.value.index == 0


def test_invalid_operation_shapes_are_rejected():
    with pytest.raises(PatchError):
        parse_operations([{"op": "explode"}])
    with pytest.raises(PatchError):
        parse_operations([{"op": "move", "id": "a"}])                 # position missing
    with pytest.raises(PatchError):
        parse_operations([{"op": "rename", "name": "x", "bogus": 1}])  # extra field


def test_duplicate_connection_self_loop_and_trigger_input_are_refused():
    doc, _ = apply_operations(empty(), ops(add("a", "manual_trigger"), add("b", "set"),
                                           {"op": "connect", "from": "a", "to": "b"}))
    with pytest.raises(PatchError, match="already connected"):
        apply_operations(doc, ops({"op": "connect", "from": "a", "to": "b"}))
    with pytest.raises(PatchError, match="itself"):
        apply_operations(doc, ops({"op": "connect", "from": "b", "to": "b"}))
    with pytest.raises(PatchError, match="trigger and takes no input"):
        apply_operations(doc, ops({"op": "connect", "from": "b", "to": "a"}))


def test_changing_a_switch_that_orphans_an_edge_is_caught():
    doc, _ = apply_operations(empty(), ops(
        add("a", "manual_trigger"),
        add("sw", "switch", parameters={"rules": [{}, {}]}), add("z", "set"),
        {"op": "connect", "from": "a", "to": "sw"},
        {"op": "connect", "from": "sw", "to": "z", "output": "case_1"}))
    with pytest.raises(PatchError, match="no output 'case_1'"):
        apply_operations(doc, ops({"op": "update_node", "id": "sw", "parameters": {"rules": [{}]}}))


def test_parameter_type_checks_allow_expressions_and_partial_drafts():
    apply_operations(empty(), ops(add("l", "limit", parameters={"max_items": "{{ $json.n }}"})))   # expression ok
    apply_operations(empty(), ops(add("l", "limit")))                                              # draft: missing ok
    with pytest.raises(PatchError, match="max_items"):
        apply_operations(empty(), ops(add("l", "limit", parameters={"max_items": "three"})))
    with pytest.raises(PatchError, match="unknown parameter 'bogus'"):
        apply_operations(empty(), ops(add("l", "limit", parameters={"bogus": 1})))


def test_patch_risk_removing_from_a_published_workflow_is_destructive():
    doc, _ = apply_operations(empty(), ops(add("a", "manual_trigger")))
    rm, mv = ops({"op": "remove_node", "id": "a"}), ops({"op": "move", "id": "a", "position": {"x": 1, "y": 1}})
    assert patch_risk(doc, rm, published=True) == "destructive"
    assert patch_risk(doc, rm, published=False) == "write"
    assert patch_risk(doc, mv, published=True) == "write"


def test_publish_checks_completeness():
    doc, _ = apply_operations(empty(), ops(add("s", "set")))
    assert any("trigger" in e for e in publish_errors(doc))
    doc, _ = apply_operations(empty(), ops(add("t", "manual_trigger"), add("g", "google_sheets__append_row")))
    errs = publish_errors(doc)
    assert any("spreadsheet_id" in e for e in errs) and any("connected" in e for e in errs)
    doc, _ = apply_operations(empty(), ops(add("t", "manual_trigger"), add("l", "limit", parameters={"max_items": 2})))
    assert publish_errors(doc) == []


# ------------------------------------------------------------------ HTTP API: versions and conflicts

def api(make_client):
    return make_client(None)


def post(c, path, body, user=USER_A):
    return c.post(path, json=body, headers=auth(user))


def test_create_patch_versions_and_conflicts(make_client):
    c = api(make_client)
    r = post(c, "/api/workflows", {"name": "Leads"})
    assert r.status_code == 201
    wf = r.json()["workflow"]
    assert wf["version"] == 1 and wf["status"] == "draft" and wf["nodes"] == []
    wid = wf["id"]

    # Editor A (chat) and editor B (canvas) both start from version 1.
    a = post(c, f"/api/workflows/{wid}/patch", {"base_version": 1, "operations": [add("t", "manual_trigger")]})
    assert a.status_code == 200 and a.json()["workflow"]["version"] == 2
    assert a.json()["changes"][0]["op"] == "add_node" and a.json()["risk"] == "write"
    b = post(c, f"/api/workflows/{wid}/patch",
             {"base_version": 1, "operations": [{"op": "rename", "name": "B's rename"}]})
    assert b.status_code == 409
    detail = b.json()["detail"]
    assert detail["current"]["version"] == 2 and [n["id"] for n in detail["current"]["nodes"]] == ["t"]
    assert c.get(f"/api/workflows/{wid}", headers=auth()).json()["workflow"]["name"] == "Leads"   # B did not write

    # B re-applies on top of the latest version.
    b = post(c, f"/api/workflows/{wid}/patch", {"base_version": 2, "operations": [{"op": "rename", "name": "B"}]})
    assert b.status_code == 200 and b.json()["workflow"]["version"] == 3

    versions = c.get(f"/api/workflows/{wid}/versions", headers=auth()).json()
    assert [v["version"] for v in versions] == [3, 2, 1]
    v2 = c.get(f"/api/workflows/{wid}/versions/2", headers=auth()).json()["workflow"]
    assert v2["name"] == "Leads" and len(v2["nodes"]) == 1
    assert c.get(f"/api/workflows/{wid}/versions/9", headers=auth()).status_code == 404


def test_failed_patch_changes_nothing_and_reports_the_operation(make_client, db):
    c = api(make_client)
    wid = post(c, "/api/workflows", {"name": "W"}).json()["workflow"]["id"]
    r = post(c, f"/api/workflows/{wid}/patch",
             {"base_version": 1, "operations": [add("a", "manual_trigger"), add("b", "nope")]})
    assert r.status_code == 422
    assert r.json()["detail"]["operation_index"] == 1 and "unknown node type" in r.json()["detail"]["message"]
    wf = c.get(f"/api/workflows/{wid}", headers=auth()).json()["workflow"]
    assert wf["version"] == 1 and wf["nodes"] == []
    assert len(db.tables["workflow_versions"]) == 1


def test_compare_and_swap_catches_a_race_between_read_and_write(make_client, db, monkeypatch):
    """Two editors both pass the version check; only one write may win."""
    c = api(make_client)
    wid = post(c, "/api/workflows", {"name": "W"}).json()["workflow"]["id"]
    real_update = db.update
    raced = {"done": False}

    async def racing_update(table, filters, values):
        if table == "workflows" and not raced["done"]:
            raced["done"] = True
            await real_update("workflows", {"id": wid}, {"version": 2})      # the other editor commits first
        return await real_update(table, filters, values)

    monkeypatch.setattr(db, "update", racing_update)
    r = post(c, f"/api/workflows/{wid}/patch", {"base_version": 1, "operations": [{"op": "rename", "name": "X"}]})
    assert r.status_code == 409 and r.json()["detail"]["current"]["version"] == 2
    assert db.tables["workflows"][0]["name"] == "W"                            # the loser wrote nothing


def test_create_with_initial_operations_and_other_users_cannot_see_it(make_client):
    c = api(make_client)
    r = post(c, "/api/workflows", {"name": "Built by chat", "operations": [
        add("t", "manual_trigger"), add("s", "set"), {"op": "connect", "from": "t", "to": "s"}]})
    wf = r.json()["workflow"]
    assert len(wf["nodes"]) == 2 and len(wf["edges"]) == 1
    wid = wf["id"]
    assert c.get(f"/api/workflows/{wid}", headers=auth(USER_B)).status_code == 404
    assert post(c, f"/api/workflows/{wid}/patch", {"base_version": 1, "operations": [
        {"op": "rename", "name": "hax"}]}, USER_B).status_code == 404
    assert c.get("/api/workflows", headers=auth(USER_B)).json() == []
    assert c.delete(f"/api/workflows/{wid}", headers=auth(USER_B)).status_code == 404
    assert c.get("/api/workflows", headers=auth()).json()[0]["node_count"] == 2


async def test_connection_must_belong_to_the_user_and_the_app(make_client, db, store):
    mine = await connect(db, store, "google_sheets")
    theirs = await connect(db, store, "google_sheets", user=USER_B, label="other")
    slack = await connect(db, store, "slack")
    c = api(make_client)
    wid = post(c, "/api/workflows", {"name": "W"}).json()["workflow"]["id"]
    node = lambda conn: add("g", "google_sheets__get_values", connection_id=conn["id"])   # noqa: E731
    assert post(c, f"/api/workflows/{wid}/patch", {"base_version": 1, "operations": [node(theirs)]}).status_code == 422
    r = post(c, f"/api/workflows/{wid}/patch", {"base_version": 1, "operations": [node(slack)]})
    assert r.status_code == 422 and "not google_sheets" in r.json()["detail"]["message"]
    assert post(c, f"/api/workflows/{wid}/patch", {"base_version": 1, "operations": [node(mine)]}).status_code == 200


async def test_publish_unpublish_and_published_snapshot(make_client, db, store):
    c = api(make_client)
    wid = post(c, "/api/workflows", {"name": "W", "operations": [add("g", "google_sheets__get_values")]}
               ).json()["workflow"]["id"]
    r = post(c, f"/api/workflows/{wid}/publish", {})
    assert r.status_code == 422 and "trigger" in r.json()["detail"]["message"]

    conn = await connect(db, store, "google_sheets")
    post(c, f"/api/workflows/{wid}/patch", {"base_version": 1, "operations": [
        add("t", "manual_trigger"), {"op": "connect", "from": "t", "to": "g"},
        {"op": "update_node", "id": "g", "connection_id": conn["id"],
         "parameters": {"spreadsheet_id": "abc", "range": "A1:B2"}}]})
    r = post(c, f"/api/workflows/{wid}/publish", {})
    assert r.status_code == 200 and r.json()["workflow"]["status"] == "published"
    row = db.tables["workflows"][0]
    assert row["published_version"] == 2

    # Editing after publishing creates a newer draft; the published snapshot is untouched.
    post(c, f"/api/workflows/{wid}/patch", {"base_version": 2, "operations": [{"op": "rename", "name": "Later"}]})
    from app.workflows.service import WorkflowService

    snap = await WorkflowService(db).published_document(USER_A, wid)
    assert snap["version"] == 2 and snap["name"] == "W"
    assert c.get(f"/api/workflows/{wid}", headers=auth()).json()["published_version"] == 2

    r = post(c, f"/api/workflows/{wid}/unpublish", {})
    assert r.json()["workflow"]["status"] == "draft"
    assert await WorkflowService(db).published_document(USER_A, wid) is None


async def test_removing_a_node_from_a_published_workflow_reports_destructive(make_client, db, store):
    c = api(make_client)
    wid = post(c, "/api/workflows", {"name": "W", "operations": [
        add("t", "manual_trigger"), add("l", "limit", parameters={"max_items": 1}),
        {"op": "connect", "from": "t", "to": "l"}]}).json()["workflow"]["id"]
    assert post(c, f"/api/workflows/{wid}/publish", {}).status_code == 200
    r = post(c, f"/api/workflows/{wid}/patch", {"base_version": 1, "operations": [{"op": "remove_node", "id": "l"}]})
    assert r.status_code == 200 and r.json()["risk"] == "destructive"


def test_delete_workflow_removes_versions(make_client, db):
    c = api(make_client)
    wid = post(c, "/api/workflows", {"name": "W"}).json()["workflow"]["id"]
    assert c.delete(f"/api/workflows/{wid}", headers=auth()).json() == {"ok": True}
    assert db.tables["workflows"] == [] and db.tables["workflow_versions"] == []
    assert c.get(f"/api/workflows/{wid}", headers=auth()).status_code == 404


def test_node_types_and_schema_endpoints(make_client):
    c = api(make_client)
    types = c.get("/api/node-types", headers=auth()).json()
    by = {t["type"]: t for t in types}
    assert by["if"]["outputs"] == ["true", "false"] and by["google_sheets__append_row"]["needs_connection"]
    assert by["switch"]["dynamic_outputs"] is True and by["http_request"]["dynamic_risk"] is True
    assert c.get("/api/node-types").status_code == 401
    assert c.get("/api/workflow-schema").json()["title"] == "Workflow"


def test_rls_policies_exist_for_every_new_table():
    from app.core.config import REPO_ROOT

    sql = (REPO_ROOT / "supabase" / "migrations" / "0007_workflows.sql").read_text()
    for table in ("workflows", "workflow_versions", "executions", "node_executions", "execution_approvals",
                  "triggers"):
        assert f"alter table public.{table} enable row level security" in sql
    assert "skip locked" in sql.lower()
