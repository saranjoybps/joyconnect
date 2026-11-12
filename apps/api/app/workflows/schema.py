"""Workflow validation: the shared JSON Schema first, then the rules a schema cannot express."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator

from app.core.config import REPO_ROOT
from app.workflows.registry import MAIN, NodeRegistry, NodeType, get_registry
from app.workflows.schedule import validate_config

SCHEMA_PATH = REPO_ROOT / "schemas" / "workflow.schema.json"
Doc = dict[str, Any]


@lru_cache
def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def is_expression(value: Any) -> bool:
    return isinstance(value, str) and "{{" in value


def schema_errors(doc: Doc) -> list[str]:
    """Violations of schemas/workflow.schema.json, as 'path: message' lines."""
    out = []
    for e in sorted(_validator().iter_errors(doc), key=lambda e: list(map(str, e.absolute_path))):
        path = "/".join(str(p) for p in e.absolute_path) or "(root)"
        out.append(f"{path}: {e.message}")
    return out


def parameter_errors(nt: NodeType, params: dict[str, Any]) -> list[str]:
    """Type-check the parameters that are present. Missing ones are fine in a draft (see publish_errors).
    A value containing {{ }} is an expression and is checked when it runs."""
    props = nt.parameters.get("properties", {})
    out = []
    for key, value in params.items():
        sub = props.get(key)
        if sub is None:
            out.append(f"unknown parameter '{key}'")
        elif not is_expression(value):
            for e in Draft202012Validator(sub).iter_errors(value):
                out.append(f"parameter '{key}': {e.message}")
                break
    return out


def structural_errors(doc: Doc, registry: NodeRegistry | None = None) -> list[str]:
    """What the schema cannot say: unique ids and names, known node types, valid parameters, and edges that
    point at real nodes, real outputs and real inputs."""
    registry = registry or get_registry()
    errs: list[str] = []
    by_id: dict[str, Doc] = {}
    names: set[str] = set()
    for n in doc["nodes"]:
        if n["id"] in by_id:
            errs.append(f"duplicate node id '{n['id']}'")
        by_id[n["id"]] = n
        if n["name"] in names:
            errs.append(f"duplicate node name '{n['name']}' (names are used in expressions and must be unique)")
        names.add(n["name"])
        nt = registry.get(n["type"])
        if nt is None:
            errs.append(f"node '{n['name']}': unknown node type '{n['type']}'")
            continue
        errs += [f"node '{n['name']}': {m}" for m in parameter_errors(nt, n["parameters"])]
        if nt.connector is None and n.get("connection_id"):
            errs.append(f"node '{n['name']}': {nt.name} does not use a connection")
    seen: set[tuple[str, str, str, str]] = set()
    for e in doc["edges"]:
        src, dst = by_id.get(e["from"]), by_id.get(e["to"])
        if src is None or dst is None:
            errs.append(f"edge {e['from']} -> {e['to']}: node does not exist")
            continue
        if e["from"] == e["to"]:
            errs.append(f"edge on '{src['name']}': a node cannot connect to itself")
        key = (e["from"], e["output"], e["to"], e.get("input", MAIN))
        if key in seen:
            errs.append(f"duplicate edge {src['name']}.{e['output']} -> {dst['name']}")
        seen.add(key)
        snt, dnt = registry.get(src["type"]), registry.get(dst["type"])
        if snt is not None and e["output"] not in snt.output_names(src["parameters"]):
            errs.append(f"edge {src['name']} -> {dst['name']}: '{src['name']}' has no output '{e['output']}' "
                        f"(has: {', '.join(snt.output_names(src['parameters'])) or 'none'})")
        if dnt is not None:
            if not dnt.inputs:
                errs.append(f"edge {src['name']} -> {dst['name']}: '{dst['name']}' is a trigger and takes no input")
            elif e.get("input", MAIN) not in dnt.inputs:
                errs.append(f"edge {src['name']} -> {dst['name']}: '{dst['name']}' has no input "
                            f"'{e.get('input', MAIN)}' (has: {', '.join(dnt.inputs)})")
    return errs


def document_errors(doc: Doc, registry: NodeRegistry | None = None) -> list[str]:
    errs = schema_errors(doc)
    return errs or structural_errors(doc, registry)


def _allows_null(sub: dict[str, Any]) -> bool:
    t = sub.get("type")
    return t == "null" or (isinstance(t, list) and "null" in t) or "type" not in sub


def publish_errors(doc: Doc, registry: NodeRegistry | None = None) -> list[str]:
    """Extra checks before a workflow may run unattended: it must be complete."""
    registry = registry or get_registry()
    errs = document_errors(doc, registry)
    if errs:
        return errs
    if not any((registry.get(n["type"]) or NodeType("", "", "")).is_trigger for n in doc["nodes"]):
        errs.append("add a trigger node (Manual, Schedule, Webhook or Error Trigger)")
    for n in doc["nodes"]:
        if n.get("disabled"):
            continue
        nt = registry.get(n["type"])
        if nt is None:
            continue
        props = nt.parameters.get("properties", {})
        required = set(nt.parameters.get("required", []))
        if nt.strict_parameters:
            required |= {k for k, sub in props.items() if not _allows_null(sub)}
        for key in sorted(required):
            if n["parameters"].get(key) is None:
                errs.append(f"node '{n['name']}': parameter '{key}' is required")
        if n["type"] == "schedule_trigger":
            errs += [f"node '{n['name']}': {m}" for m in validate_config(n["parameters"])]
        if n["type"] == "webhook_trigger" and n["parameters"].get("authentication") == "header":
            hn = str(n["parameters"].get("header_name") or "X-Webhook-Secret")
            if not hn.replace("-", "").isalnum():
                errs.append(f"node '{n['name']}': the header name may only contain letters, digits and dashes")
        if nt.connector and not n.get("connection_id"):
            errs.append(f"node '{n['name']}': choose which connected {nt.connector.replace('_', ' ')} account to use")
    return errs
