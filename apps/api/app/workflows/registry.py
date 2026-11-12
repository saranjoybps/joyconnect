"""Node registry: every node type a workflow can use. The canvas palette and config panels are generated
from `GET /api/node-types`, which serialises this registry.

Core nodes are modeled on n8n (docs.n8n.io, core nodes). App nodes are generated, one per connector tool, from the
existing connector manifests: the node `type` is the tool name, its parameters are the tool's JSON schema, its risk
is the tool's risk. Handlers live in `app/workflows/handlers.py`, not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.connectors.base import Risk
from app.connectors.registry import all_manifests

Category = str  # trigger | flow | data | app | ai | human

MAIN = "main"
EXPR_NOTE = "Any value may be an expression such as {{ $json.email }}."

CONDITIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "Conditions",
    "properties": {
        "combinator": {"enum": ["and", "or"], "default": "and"},
        "ignore_case": {"type": "boolean", "default": False},
        "loose_types": {"type": "boolean", "default": False},
        "items": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "left": {},
                "type": {"enum": ["string", "number", "boolean", "datetime", "array", "object"]},
                "op": {"type": "string"},
                "right": {},
            },
            "required": ["left", "type", "op"],
        }},
    },
}


@dataclass
class NodeType:
    type: str
    name: str
    category: Category
    description: str
    parameters: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    inputs: list[str] = field(default_factory=lambda: [MAIN])
    outputs: list[str] | Callable[[dict[str, Any]], list[str]] = field(default_factory=lambda: [MAIN])
    risk: Risk | Callable[[dict[str, Any]], Risk] = "read"
    icon: str = "box"
    connector: str | None = None        # app nodes: the connector id (selects connection_id)
    tool: str | None = None
    wait_for_all_inputs: bool = False   # Merge waits for every connected input
    strict_parameters: bool = False     # app nodes: unknown keys are errors
    ui: dict[str, dict[str, Any]] = field(default_factory=dict)   # app nodes: parameter -> how the canvas edits it

    @property
    def is_trigger(self) -> bool:
        return self.category == "trigger"

    def output_names(self, parameters: dict[str, Any] | None = None) -> list[str]:
        return self.outputs(parameters or {}) if callable(self.outputs) else list(self.outputs)

    def risk_of(self, parameters: dict[str, Any] | None = None) -> Risk:
        return self.risk(parameters or {}) if callable(self.risk) else self.risk

    def public_parameters(self) -> dict[str, Any]:
        """The parameter schema for the canvas: each parameter that loads options carries an `x-ui` hint."""
        if not self.ui:
            return self.parameters
        props = {k: ({**v, "x-ui": self.ui[k]} if k in self.ui else v)
                 for k, v in self.parameters.get("properties", {}).items()}
        return {**self.parameters, "properties": props}

    def to_public(self) -> dict[str, Any]:
        res, op = split_action(self.tool) if self.tool else (None, None)
        return {
            "resource": res, "operation": op,
            "type": self.type, "name": self.name, "category": self.category, "description": self.description,
            "parameters": self.public_parameters(), "inputs": self.inputs, "outputs": self.output_names({}),
            "dynamic_outputs": callable(self.outputs), "risk": self.risk_of({}) if not callable(self.risk) else "read",
            "dynamic_risk": callable(self.risk), "icon": self.icon, "connector": self.connector,
            "needs_connection": self.connector is not None,
        }


_VERBS = ["comment_on", "list", "get", "search", "create", "add", "append", "update", "delete", "clear", "send",
          "post", "upload", "complete", "query", "replace", "insert"]


def _singular(word: str) -> str:
    if word.endswith("ies"):
        return word[:-3] + "y"
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


def split_action(tool_name: str) -> tuple[str, str]:
    """"google_sheets__append_row" -> ("Row", "Append"). The Resource and Operation dropdowns of an app node are
    derived from the tool names, so every connector gets them without per-tool configuration."""
    action = tool_name.split("__", 1)[1]
    for verb in _VERBS:
        if action.startswith(verb + "_") and len(action) > len(verb) + 1:
            words = action[len(verb) + 1:].split("_")
            words[-1] = _singular(words[-1])
            noun = " ".join(words)
            return noun[:1].upper() + noun[1:], verb.replace("_", " ").capitalize()
    text = action.replace("_", " ")
    return text[:1].upper() + text[1:], "Run"


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


# ---------------------------------------------------------------------------------------------- core nodes

def _switch_outputs(p: dict[str, Any]) -> list[str]:
    if p.get("mode") == "expression":
        n = int(p.get("number_of_outputs") or 2)
        return [f"case_{i}" for i in range(max(1, min(n, 20)))]
    n = len(p.get("rules") or []) or 1
    outs = [f"case_{i}" for i in range(n)]
    return outs + ["fallback"] if p.get("fallback") == "extra" else outs


def _http_risk(p: dict[str, Any]) -> Risk:
    return "read" if str(p.get("method", "GET")).upper() in ("GET", "HEAD", "OPTIONS") else "write"


CORE_NODES: list[NodeType] = [
    # ---- triggers
    NodeType("manual_trigger", "Manual Trigger", "trigger", "Starts the workflow when you click Run.",
             inputs=[], icon="play"),
    NodeType("schedule_trigger", "Schedule Trigger", "trigger",
             "Runs the published workflow on a schedule: every N seconds, minutes, hours, days, weeks, months, or a cron expression.",
             _obj({
                 "timezone": {"type": "string", "default": "UTC", "description": "IANA zone, e.g. Europe/Paris"},
                 "rules": {"type": "array", "minItems": 1, "items": _obj({
                     "interval": {"enum": ["seconds", "minutes", "hours", "days", "weeks", "months", "cron"]},
                     "every": {"type": "integer", "minimum": 1, "default": 1},
                     "minute": {"type": "integer", "minimum": 0, "maximum": 59},
                     "hour": {"type": "integer", "minimum": 0, "maximum": 23},
                     "weekdays": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 6},
                                  "description": "0 = Sunday"},
                     "day_of_month": {"type": "integer", "minimum": 1, "maximum": 31},
                     "expression": {"type": "string", "description": "5-field cron, or 6 with seconds first"},
                 }, ["interval"])},
             }, ["rules"]), inputs=[], icon="clock"),
    NodeType("webhook_trigger", "Webhook", "trigger",
             "Starts the workflow when an HTTP request reaches its URL (published workflows only).",
             _obj({
                 "http_method": {"enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"], "default": "POST"},
                 "authentication": {"enum": ["none", "header"], "default": "none"},
                 "header_name": {"type": "string", "default": "X-Webhook-Secret",
                                 "description": "The secret is generated for you when you publish (shown once)."},
                 "response_mode": {"enum": ["immediately", "last_node", "respond_node"], "default": "immediately"},
                 "response_code": {"type": "integer", "minimum": 100, "maximum": 599, "default": 200},
             }), inputs=[], icon="webhook"),
    NodeType("error_trigger", "Error Trigger", "trigger",
             "Starts when another workflow that names this one as its error workflow fails.",
             inputs=[], icon="alert"),
    # ---- flow
    NodeType("if", "IF", "flow", "Routes items to the true or false output by conditions.",
             _obj({"conditions": CONDITIONS_SCHEMA}, ["conditions"]), outputs=["true", "false"], icon="split"),
    NodeType("switch", "Switch", "flow", "Routes items to one of several outputs (rules or an expression).",
             _obj({
                 "mode": {"enum": ["rules", "expression"], "default": "rules"},
                 "rules": {"type": "array", "items": _obj({"conditions": CONDITIONS_SCHEMA, "name": {"type": "string"}})},
                 "fallback": {"enum": ["none", "extra", "output_0"], "default": "none"},
                 "all_matching": {"type": "boolean", "default": False,
                                  "description": "Send each item to every matching output, not only the first"},
                 "expression": {"description": "Expression returning the output index (expression mode)"},
                 "number_of_outputs": {"type": "integer", "minimum": 1, "maximum": 20, "default": 2},
             }), outputs=_switch_outputs, icon="route"),
    NodeType("merge", "Merge", "flow", "Combines the items of two inputs.",
             _obj({
                 "mode": {"enum": ["append", "combine_by_fields", "combine_by_position", "all_combinations",
                                   "choose_branch"], "default": "append"},
                 "fields": {"type": "array", "items": _obj({"field1": {"type": "string"}, "field2": {"type": "string"}})},
                 "output_type": {"enum": ["matches", "non_matches", "everything", "input1", "input2"],
                                 "default": "matches", "description": "combine_by_fields: which items are kept"},
                 "clash": {"enum": ["prefer_input2", "prefer_input1", "add_suffix"], "default": "prefer_input2"},
                 "choose": {"enum": ["input1", "input2", "empty"], "default": "input1"},
                 "multiple_matches": {"enum": ["all", "first"], "default": "all"},
             }), inputs=["input1", "input2"], wait_for_all_inputs=True, icon="merge"),
    NodeType("loop_over_items", "Loop Over Items", "flow",
             "Processes items in batches. Connect the end of the loop back to this node's input; the done output runs once at the end.",
             _obj({"batch_size": {"type": "integer", "minimum": 1, "default": 1}}),
             outputs=["loop", "done"], icon="repeat"),
    NodeType("wait", "Wait", "flow", "Pauses the run, then resumes it.",
             _obj({
                 "mode": {"enum": ["interval", "time"], "default": "interval"},
                 "amount": {"type": "number", "minimum": 0},
                 "unit": {"enum": ["seconds", "minutes", "hours", "days"], "default": "seconds"},
                 "resume_at": {"type": "string", "description": "ISO 8601 date-time (time mode)"},
             }), icon="hourglass"),
    NodeType("filter", "Filter", "flow", "Keeps only the items that meet the conditions.",
             _obj({"conditions": CONDITIONS_SCHEMA}, ["conditions"]), icon="filter"),
    NodeType("stop_and_error", "Stop and Error", "flow", "Fails the run on purpose, with your message.",
             _obj({
                 "error_type": {"enum": ["message", "object"], "default": "message"},
                 "message": {"type": "string"},
                 "error_object": {"type": "object"},
             }), outputs=[], icon="octagon"),
    NodeType("execute_sub_workflow", "Sub-workflow", "flow", "Runs another of your workflows and waits for its result.",
             _obj({
                 "workflow_id": {"type": "string"},
                 "mode": {"enum": ["all_items", "each_item"], "default": "all_items"},
             }, ["workflow_id"]), icon="workflow"),
    # ---- data
    NodeType("set", "Edit Fields (Set)", "data", "Sets or overwrites fields on each item.",
             _obj({
                 "mode": {"enum": ["manual", "json"], "default": "manual"},
                 "fields": {"type": "array", "items": _obj({
                     "name": {"type": "string"}, "value": {},
                     "type": {"enum": ["string", "number", "boolean", "array", "object", "auto"], "default": "auto"}},
                     ["name"])},
                 "json": {"description": "JSON object (or expression) merged into each item (json mode)"},
                 "keep_only_set": {"type": "boolean", "default": False},
                 "dot_notation": {"type": "boolean", "default": True},
             }), icon="pencil"),
    NodeType("aggregate", "Aggregate", "data", "Groups items into one item.",
             _obj({
                 "mode": {"enum": ["individual_fields", "all_item_data"], "default": "individual_fields"},
                 "fields": {"type": "array", "items": _obj({"field": {"type": "string"}, "rename": {"type": "string"}},
                                                           ["field"])},
                 "destination_field": {"type": "string", "default": "data"},
                 "include": {"enum": ["all", "specified", "except"], "default": "all"},
                 "include_fields": {"type": "array", "items": {"type": "string"}},
                 "merge_lists": {"type": "boolean", "default": False},
                 "keep_missing": {"type": "boolean", "default": False},
             }), icon="layers"),
    NodeType("split_out", "Split Out", "data", "Turns a list field into one item per entry.",
             _obj({
                 "field": {"type": "string"},
                 "include": {"enum": ["none", "all", "selected"], "default": "none"},
                 "include_fields": {"type": "array", "items": {"type": "string"}},
                 "destination_field": {"type": "string"},
             }, ["field"]), icon="expand"),
    NodeType("sort", "Sort", "data", "Orders the items (or shuffles them).",
             _obj({
                 "type": {"enum": ["simple", "random"], "default": "simple"},
                 "fields": {"type": "array", "items": _obj({"field": {"type": "string"},
                                                            "order": {"enum": ["asc", "desc"], "default": "asc"}},
                                                           ["field"])},
             }), icon="sort"),
    NodeType("limit", "Limit", "data", "Keeps only the first or last N items.",
             _obj({"max_items": {"type": "integer", "minimum": 0, "default": 1},
                   "keep": {"enum": ["first", "last"], "default": "first"}}, ["max_items"]), icon="scissors"),
    NodeType("http_request", "HTTP Request", "data",
             "Calls any HTTP API. GET/HEAD/OPTIONS are reads; every other method is a write and needs approval.",
             _obj({
                 "method": {"enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"], "default": "GET"},
                 "url": {"type": "string"},
                 "headers": {"type": "object"},
                 "query": {"type": "object"},
                 "body_type": {"enum": ["none", "json", "form", "raw"], "default": "none"},
                 "body": {},
                 "response_format": {"enum": ["autodetect", "json", "text"], "default": "autodetect"},
                 "timeout_ms": {"type": "integer", "minimum": 100, "maximum": 120000, "default": 30000},
                 "ignore_errors": {"type": "boolean", "default": False,
                                   "description": "Do not fail on HTTP error codes; return the status instead"},
             }, ["url"]), risk=_http_risk, icon="globe"),
    NodeType("respond_to_webhook", "Respond to Webhook", "data",
             "Sets the response a webhook caller receives (Webhook response mode: respond_node).",
             _obj({
                 "respond_with": {"enum": ["all_items", "first_item", "json", "text", "redirect", "no_data"],
                                  "default": "first_item"},
                 "body": {},
                 "response_code": {"type": "integer", "minimum": 100, "maximum": 599, "default": 200},
                 "headers": {"type": "object"},
                 "redirect_url": {"type": "string"},
             }), icon="reply"),
]


# ---------------------------------------------------------------------------------------------- registry

class NodeRegistry:
    def __init__(self, nodes: list[NodeType]):
        self._by_type = {n.type: n for n in nodes}
        if len(self._by_type) != len(nodes):
            raise RuntimeError("duplicate node type in registry")

    def get(self, node_type: str) -> NodeType | None:
        return self._by_type.get(node_type)

    def all(self) -> list[NodeType]:
        return list(self._by_type.values())

    def public(self) -> list[dict[str, Any]]:
        return [n.to_public() for n in self.all()]


def _app_nodes() -> list[NodeType]:
    out: list[NodeType] = []
    for m in all_manifests().values():
        for t in m.tools:
            action = t.name.split("__", 1)[1].replace("_", " ")
            out.append(NodeType(
                type=t.name, name=f"{m.name}: {action[:1].upper()}{action[1:]}", category="app",
                description=f"{t.description} {EXPR_NOTE}", parameters=t.parameters, risk=t.risk, icon=m.icon,
                connector=m.id, tool=t.name, strict_parameters=True, ui=m.param_ui.get(t.name, {})))
    return out


_registry: NodeRegistry | None = None


def get_registry() -> NodeRegistry:
    """Core nodes plus one app node per connector tool. Built once; call reset_registry() in tests."""
    global _registry
    if _registry is None:
        _registry = NodeRegistry(CORE_NODES + _app_nodes() + _extra_nodes())
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None


def _extra_nodes() -> list[NodeType]:
    """AI and human nodes are added in step 7."""
    return []
