"""The ONE way to edit a workflow. Chat, canvas and API all send these operations to the patch endpoint.

`apply_operations` is pure: it takes a workflow document and a list of operations and returns the new document, or
raises PatchError naming the failing operation. All operations apply or none do. Structural validation runs once on
the final document, so an operation list may pass through temporarily invalid states (for example removing and
re-adding an output).
"""

from __future__ import annotations

import copy
import uuid
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from app.workflows.registry import MAIN, NodeRegistry, get_registry
from app.workflows.schema import document_errors

Doc = dict[str, Any]


class PatchError(Exception):
    def __init__(self, message: str, index: int | None = None, errors: list[str] | None = None):
        super().__init__(message)
        self.index, self.errors = index, errors or [message]


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float
    y: float


class NewNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = None
    type: str
    name: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    position: Position | None = None
    connection_id: str | None = None
    settings: dict[str, Any] | None = None
    pinned_data: list[dict[str, Any]] | None = None
    disabled: bool | None = None


class AddNode(_Op):
    op: Literal["add_node"]
    node: NewNode


class UpdateNode(_Op):
    op: Literal["update_node"]
    id: str                                   # node id, or its exact name
    name: str | None = None
    type: str | None = None                   # switch an app node to another operation of the same connector
    parameters: dict[str, Any] | None = None  # merged into the existing parameters (shallow)
    remove_parameters: list[str] | None = None  # keys deleted from the parameters (used to clear dependent fields)
    replace: bool = False                     # True: `parameters` replaces them instead
    connection_id: str | None = None
    settings: dict[str, Any] | None = None
    pinned_data: list[dict[str, Any]] | None = None
    disabled: bool | None = None
    clear_connection: bool = False
    clear_pinned_data: bool = False


class RemoveNode(_Op):
    op: Literal["remove_node"]
    id: str


class Connect(_Op):
    op: Literal["connect"]
    from_: str = Field(alias="from")
    to: str
    output: str = MAIN
    input: str = MAIN

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Disconnect(_Op):
    op: Literal["disconnect"]
    from_: str = Field(alias="from")
    to: str
    output: str | None = None
    input: str | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Rename(_Op):
    op: Literal["rename"]
    name: str = Field(min_length=1, max_length=200)
    id: str | None = None                     # a node; omit to rename the workflow


class Move(_Op):
    op: Literal["move"]
    id: str
    position: Position


class SetSettings(_Op):
    op: Literal["set_settings"]
    settings: dict[str, Any]                  # merged into the workflow settings


Operation = Annotated[Union[AddNode, UpdateNode, RemoveNode, Connect, Disconnect, Rename, Move, SetSettings],
                      Field(discriminator="op")]
_ops = TypeAdapter(list[Operation])


def parse_operations(raw: list[dict[str, Any]]) -> list[Any]:
    try:
        return _ops.validate_python(raw)
    except ValidationError as exc:
        e = exc.errors()[0]
        idx = e["loc"][0] if e["loc"] and isinstance(e["loc"][0], int) else None
        where = ".".join(str(p) for p in e["loc"][1:]) or "operation"
        raise PatchError(f"operation {idx}: {where}: {e['msg']}", idx) from exc


def _find(doc: Doc, ref: str, index: int) -> Doc:
    for n in doc["nodes"]:
        if n["id"] == ref:
            return n
    named = [n for n in doc["nodes"] if n["name"] == ref]
    if len(named) == 1:
        return named[0]
    raise PatchError(f"operation {index}: no node with id or name '{ref}'", index)


def _new_id(doc: Doc) -> str:
    taken = {n["id"] for n in doc["nodes"]}
    while (nid := f"n_{uuid.uuid4().hex[:8]}") in taken:
        pass
    return nid


def _unique_name(doc: Doc, base: str) -> str:
    names = {n["name"] for n in doc["nodes"]}
    if base not in names:
        return base
    i = 2
    while f"{base} {i}" in names:
        i += 1
    return f"{base} {i}"


def _next_position(doc: Doc) -> dict[str, float]:
    if not doc["nodes"]:
        return {"x": 0.0, "y": 0.0}
    right = max(doc["nodes"], key=lambda n: n["position"]["x"])
    return {"x": right["position"]["x"] + 260.0, "y": right["position"]["y"]}


def apply_operations(doc: Doc, operations: list[Any], registry: NodeRegistry | None = None) -> tuple[Doc, list[dict]]:
    """Returns (new document, change log). The input document is not modified."""
    registry = registry or get_registry()
    out = copy.deepcopy(doc)
    log: list[dict[str, Any]] = []
    for i, op in enumerate(operations):
        if isinstance(op, AddNode):
            n = op.node
            nt = registry.get(n.type)
            if nt is None:
                raise PatchError(f"operation {i}: unknown node type '{n.type}'", i)
            nid = n.id or _new_id(out)
            if any(x["id"] == nid for x in out["nodes"]):
                raise PatchError(f"operation {i}: node id '{nid}' already exists", i)
            node: Doc = {
                "id": nid, "type": n.type, "name": _unique_name(out, n.name or nt.name),
                "parameters": n.parameters, "position": n.position.model_dump() if n.position else _next_position(out),
            }
            if n.connection_id:
                node["connection_id"] = n.connection_id
            if n.settings:
                node["settings"] = n.settings
            if n.pinned_data:
                node["pinned_data"] = n.pinned_data
            if n.disabled is not None:
                node["disabled"] = n.disabled
            out["nodes"].append(node)
            log.append({"op": "add_node", "id": nid, "name": node["name"], "type": n.type})
        elif isinstance(op, UpdateNode):
            node = _find(out, op.id, i)
            if op.name is not None:
                node["name"] = op.name
            if op.type is not None and op.type != node["type"]:
                old, new = registry.get(node["type"]), registry.get(op.type)
                if new is None:
                    raise PatchError(f"operation {i}: unknown node type '{op.type}'", i)
                if old is None or old.connector is None or old.connector != new.connector:
                    raise PatchError(f"operation {i}: a node can only switch to another operation of the same app", i)
                keep = set(new.parameters.get("properties", {}))
                node["type"] = op.type
                node["parameters"] = {k: v for k, v in node["parameters"].items() if k in keep}
            for key in op.remove_parameters or []:
                node["parameters"].pop(key, None)
            if op.parameters is not None:
                node["parameters"] = dict(op.parameters) if op.replace else {**node["parameters"], **op.parameters}
            if op.clear_connection:
                node.pop("connection_id", None)
            elif op.connection_id is not None:
                node["connection_id"] = op.connection_id
            if op.settings is not None:
                node["settings"] = {**node.get("settings", {}), **op.settings}
            if op.clear_pinned_data:
                node.pop("pinned_data", None)
            elif op.pinned_data is not None:
                node["pinned_data"] = op.pinned_data
            if op.disabled is not None:
                node["disabled"] = op.disabled
            log.append({"op": "update_node", "id": node["id"], "name": node["name"]})
        elif isinstance(op, RemoveNode):
            node = _find(out, op.id, i)
            out["nodes"] = [n for n in out["nodes"] if n["id"] != node["id"]]
            out["edges"] = [e for e in out["edges"] if node["id"] not in (e["from"], e["to"])]
            log.append({"op": "remove_node", "id": node["id"], "name": node["name"], "type": node["type"]})
        elif isinstance(op, Connect):
            src, dst = _find(out, op.from_, i), _find(out, op.to, i)
            edge = {"from": src["id"], "to": dst["id"], "output": op.output}
            if op.input != MAIN:
                edge["input"] = op.input
            if any(e["from"] == edge["from"] and e["to"] == edge["to"] and e["output"] == edge["output"]
                   and e.get("input", MAIN) == op.input for e in out["edges"]):
                raise PatchError(f"operation {i}: {src['name']}.{op.output} is already connected to {dst['name']}", i)
            out["edges"].append(edge)
            log.append({"op": "connect", "from": src["id"], "to": dst["id"], "output": op.output, "input": op.input})
        elif isinstance(op, Disconnect):
            src, dst = _find(out, op.from_, i), _find(out, op.to, i)
            keep, gone = [], 0
            for e in out["edges"]:
                hit = (e["from"] == src["id"] and e["to"] == dst["id"]
                       and (op.output is None or e["output"] == op.output)
                       and (op.input is None or e.get("input", MAIN) == op.input))
                gone += hit
                if not hit:
                    keep.append(e)
            if not gone:
                raise PatchError(f"operation {i}: {src['name']} is not connected to {dst['name']}", i)
            out["edges"] = keep
            log.append({"op": "disconnect", "from": src["id"], "to": dst["id"], "removed": gone})
        elif isinstance(op, Rename):
            if op.id is None:
                out["name"] = op.name
                log.append({"op": "rename", "name": op.name})
            else:
                node = _find(out, op.id, i)
                node["name"] = op.name
                log.append({"op": "rename", "id": node["id"], "name": op.name})
        elif isinstance(op, Move):
            node = _find(out, op.id, i)
            node["position"] = op.position.model_dump()
            log.append({"op": "move", "id": node["id"]})
        elif isinstance(op, SetSettings):
            out["settings"] = {**out.get("settings", {}), **op.settings}
            log.append({"op": "set_settings", "keys": sorted(op.settings)})
    errors = document_errors(out, registry)
    if errors:
        raise PatchError("the edited workflow is not valid: " + "; ".join(errors[:5]), None, errors)
    return out, log


def patch_risk(before: Doc, operations: list[Any], published: bool) -> str:
    """'destructive' when the patch removes nodes from a published workflow (chat must get approval);
    otherwise 'write'. Edits to a draft never touch what runs unattended."""
    removes = any(isinstance(op, RemoveNode) for op in operations)
    return "destructive" if published and removes else "write"
