"""Expressions: {{ $json.field }}, {{ $node["Name"].json.field }}, {{ $("Name").item.json.x }} ...

Evaluated by our own tokenizer and parser. There is no eval, no exec, no import and no attribute access on Python
objects: the evaluator only walks dicts, lists, strings, numbers and a few wrapper objects defined below, and calls
methods only from the whitelists. Names starting with "_" are never readable. Size, depth and step limits stop
runaway expressions.

Variables: $json (current item), $input (item, first(), last(), all()), $node["Name"] and $("Name") (item/json,
first(), last(), all()), $itemIndex, $now / $today (ISO 8601 strings), $execution ({id, mode}), $workflow ({id, name}).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

MAX_EXPR_CHARS = 2_000
MAX_STEPS = 20_000
MAX_DEPTH = 40
MAX_STRING = 1_000_000


class ExpressionError(Exception):
    pass


# ------------------------------------------------------------------------------------------------ tokenizer

_TOKEN = re.compile(r"""
    \s*(?:
      (?P<num>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
     |(?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
     |(?P<id>[A-Za-z_$][A-Za-z0-9_$]*)
     |(?P<op>===|!==|==|!=|<=|>=|&&|\|\||\?\?|[-+*/%<>!?:.,()\[\]])
    )""", re.VERBOSE)
_ESC = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "/": "/"}


def _unescape(raw: str) -> str:
    body, out, i = raw[1:-1], [], 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            out.append(_ESC.get(body[i + 1], body[i + 1]))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def tokenize(src: str) -> list[tuple[str, Any]]:
    if len(src) > MAX_EXPR_CHARS:
        raise ExpressionError(f"expression is longer than {MAX_EXPR_CHARS} characters")
    out: list[tuple[str, Any]] = []
    pos = 0
    while pos < len(src):
        if src[pos:].strip() == "":
            break
        m = _TOKEN.match(src, pos)
        if not m or m.end() == pos:
            raise ExpressionError(f"unexpected character {src[pos:].strip()[:1]!r}")
        pos = m.end()
        if m.group("num") is not None:
            t = m.group("num")
            out.append(("num", float(t) if any(c in t for c in ".eE") else int(t)))
        elif m.group("str") is not None:
            out.append(("str", _unescape(m.group("str"))))
        elif m.group("id") is not None:
            out.append(("id", m.group("id")))
        else:
            out.append(("op", m.group("op")))
    out.append(("end", None))
    return out


# ------------------------------------------------------------------------------------------------ parser
# AST: ("lit", v) ("var", name) ("member", obj, name) ("index", obj, expr) ("call", fn, [args])
#      ("un", op, e) ("bin", op, a, b) ("cond", c, a, b)

class _Parser:
    def __init__(self, toks: list[tuple[str, Any]]):
        self.t, self.i = toks, 0

    def peek(self) -> tuple[str, Any]:
        return self.t[self.i]

    def take(self) -> tuple[str, Any]:
        tok = self.t[self.i]
        self.i += 1
        return tok

    def is_op(self, *ops: str) -> bool:
        k, v = self.peek()
        return k == "op" and v in ops

    def expect(self, op: str) -> None:
        if not self.is_op(op):
            raise ExpressionError(f"expected '{op}'")
        self.take()

    def parse(self):
        node = self.ternary(0)
        if self.peek()[0] != "end":
            raise ExpressionError(f"unexpected '{self.peek()[1]}'")
        return node

    def ternary(self, depth):
        self._depth(depth)
        cond = self.binary(0, depth)
        if self.is_op("?"):
            self.take()
            a = self.ternary(depth + 1)
            self.expect(":")
            b = self.ternary(depth + 1)
            return ("cond", cond, a, b)
        return cond

    _LEVELS = [("??",), ("||",), ("&&",), ("===", "!==", "==", "!="), ("<", ">", "<=", ">="), ("+", "-"),
               ("*", "/", "%")]

    def binary(self, level, depth):
        self._depth(depth)
        if level == len(self._LEVELS):
            return self.unary(depth)
        left = self.binary(level + 1, depth + 1)
        while self.is_op(*self._LEVELS[level]):
            op = self.take()[1]
            left = ("bin", op, left, self.binary(level + 1, depth + 1))
        return left

    def unary(self, depth):
        self._depth(depth)
        if self.is_op("!", "-", "+"):
            op = self.take()[1]
            return ("un", op, self.unary(depth + 1))
        return self.postfix(depth)

    def postfix(self, depth):
        node = self.primary(depth)
        while True:
            if self.is_op("."):
                self.take()
                kind, name = self.take()
                if kind != "id":
                    raise ExpressionError("expected a property name after '.'")
                node = ("member", node, name)
            elif self.is_op("["):
                self.take()
                idx = self.ternary(depth + 1)
                self.expect("]")
                node = ("index", node, idx)
            elif self.is_op("("):
                self.take()
                args = []
                if not self.is_op(")"):
                    args.append(self.ternary(depth + 1))
                    while self.is_op(","):
                        self.take()
                        args.append(self.ternary(depth + 1))
                self.expect(")")
                node = ("call", node, args)
            else:
                return node

    def primary(self, depth):
        kind, val = self.take()
        if kind in ("num", "str"):
            return ("lit", val)
        if kind == "id":
            return {"true": ("lit", True), "false": ("lit", False), "null": ("lit", None),
                    "undefined": ("lit", None)}.get(val, ("var", val))
        if kind == "op" and val == "(":
            node = self.ternary(depth + 1)
            self.expect(")")
            return node
        raise ExpressionError("unexpected end of expression" if kind == "end" else f"unexpected '{val}'")

    @staticmethod
    def _depth(d: int) -> None:
        if d > MAX_DEPTH:
            raise ExpressionError("expression is nested too deeply")


def parse(src: str):
    return _Parser(tokenize(src)).parse()


# ------------------------------------------------------------------------------------------------ context

@dataclass
class ExprContext:
    items: list[dict[str, Any]] = field(default_factory=list)          # current node's input items
    index: int = 0                                                      # current item
    nodes: Callable[[str], list[dict[str, Any]] | None] = lambda name: None   # node name -> its output items
    execution: dict[str, Any] = field(default_factory=dict)
    workflow: dict[str, Any] = field(default_factory=dict)
    now: str = ""

    def current(self) -> dict[str, Any]:
        return self.items[self.index] if 0 <= self.index < len(self.items) else {"json": {}}


class _NodeRef:
    """$node["Name"] / $("Name"): read-only view of another node's output."""

    def __init__(self, name: str, items: list[dict[str, Any]] | None, index: int):
        if items is None:
            raise ExpressionError(f"node '{name}' has not run, or does not exist")
        self.name, self.items, self.index = name, items, index

    def linked(self) -> dict[str, Any]:
        if not self.items:
            return {"json": {}}
        return self.items[self.index] if self.index < len(self.items) else self.items[0]


class _InputRef:
    def __init__(self, ctx: ExprContext):
        self.ctx = ctx


class _Fn:
    """A whitelisted function value (JSON.stringify, Math.round, obj.method ...)."""

    def __init__(self, fn: Callable[..., Any]):
        self.fn = fn


_ITEM_METHODS = {"first", "last", "all"}


def _item_method(items: list[dict[str, Any]], name: str):
    if name == "all":
        return _Fn(lambda: list(items))
    if name == "first":
        return _Fn(lambda: items[0] if items else None)
    return _Fn(lambda: items[-1] if items else None)


# ------------------------------------------------------------------------------------------------ evaluator

def _truthy(v: Any) -> bool:
    return bool(v) and v != 0 and v != ""


def _num(v: Any) -> float | int:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    if v is None or v == "":
        return 0
    if isinstance(v, str):
        try:
            f = float(v)
            return int(f) if f.is_integer() and "." not in v else f
        except ValueError:
            return math.nan
    return math.nan


def _loose_eq(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return _num(a) == _num(b) if not (isinstance(a, bool) and isinstance(b, bool)) else a == b
    if isinstance(a, (int, float)) and isinstance(b, str) or isinstance(a, str) and isinstance(b, (int, float)):
        return _num(a) == _num(b)
    return a == b


def _strict_eq(a: Any, b: Any) -> bool:
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return type(a) is type(b) and a == b


def to_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return str(v)


_STR_METHODS: dict[str, Callable[..., Any]] = {
    "toUpperCase": lambda s: s.upper(), "toLowerCase": lambda s: s.lower(), "trim": lambda s: s.strip(),
    "trimStart": lambda s: s.lstrip(), "trimEnd": lambda s: s.rstrip(),
    "includes": lambda s, x: to_text(x) in s, "startsWith": lambda s, x: s.startswith(to_text(x)),
    "endsWith": lambda s, x: s.endswith(to_text(x)), "indexOf": lambda s, x: s.find(to_text(x)),
    "split": lambda s, sep=None: [s] if sep is None else (list(s) if sep == "" else s.split(to_text(sep))),
    "slice": lambda s, a=0, b=None: s[int(a):None if b is None else int(b)],
    "substring": lambda s, a=0, b=None: s[max(int(a), 0):None if b is None else max(int(b), 0)],
    "replace": lambda s, a, b: s.replace(to_text(a), to_text(b), 1),
    "replaceAll": lambda s, a, b: s.replace(to_text(a), to_text(b)),
    "concat": lambda s, *x: s + "".join(to_text(i) for i in x), "toString": lambda s: s,
    "padStart": lambda s, n, c=" ": s.rjust(min(int(n), 10_000), to_text(c)[:1] or " "),
    "padEnd": lambda s, n, c=" ": s.ljust(min(int(n), 10_000), to_text(c)[:1] or " "),
    "repeat": lambda s, n: s * min(int(n), 1000), "charAt": lambda s, i: s[int(i)] if 0 <= int(i) < len(s) else "",
}
_LIST_METHODS: dict[str, Callable[..., Any]] = {
    "join": lambda a, sep=",": to_text(sep).join(to_text(x) for x in a),
    "includes": lambda a, x: any(_strict_eq(i, x) for i in a), "indexOf": lambda a, x: next(
        (i for i, v in enumerate(a) if _strict_eq(v, x)), -1),
    "slice": lambda a, i=0, j=None: a[int(i):None if j is None else int(j)], "concat": lambda a, *x: a + [
        y for z in x for y in (z if isinstance(z, list) else [z])],
    "at": lambda a, i: a[int(i)] if -len(a) <= int(i) < len(a) else None, "reverse": lambda a: list(reversed(a)),
    "toString": lambda a: ",".join(to_text(x) for x in a),
}
_NUM_METHODS: dict[str, Callable[..., Any]] = {
    "toFixed": lambda n, d=0: f"{n:.{int(d)}f}", "toString": lambda n: to_text(n),
}
_DICT_METHODS: dict[str, Callable[..., Any]] = {
    "hasOwnProperty": lambda d, k: to_text(k) in d,
}
_GLOBALS: dict[str, Any] = {
    "JSON": {"stringify": _Fn(lambda v, *_: json.dumps(v, ensure_ascii=False, default=str)),
             "parse": _Fn(lambda s: json.loads(s))},
    "Math": {"round": _Fn(lambda x: math.floor(_num(x) + 0.5)), "floor": _Fn(lambda x: math.floor(_num(x))),
             "ceil": _Fn(lambda x: math.ceil(_num(x))), "abs": _Fn(lambda x: abs(_num(x))),
             "min": _Fn(lambda *a: min(_num(x) for x in a)), "max": _Fn(lambda *a: max(_num(x) for x in a))},
    "Number": _Fn(lambda v: _num(v)), "String": _Fn(lambda v: to_text(v)),
    "Boolean": _Fn(lambda v: _truthy(v)), "parseInt": _Fn(lambda v, *_: int(_num(v)) if _num(v) == _num(v) else None),
    "parseFloat": _Fn(lambda v: _num(v)),
}


class _Eval:
    def __init__(self, ctx: ExprContext):
        self.ctx, self.steps = ctx, 0

    def run(self, node) -> Any:
        self.steps += 1
        if self.steps > MAX_STEPS:
            raise ExpressionError("expression took too many steps")
        kind = node[0]
        if kind == "lit":
            return node[1]
        if kind == "var":
            return self.var(node[1])
        if kind == "member":
            return self.member(self.run(node[1]), node[2])
        if kind == "index":
            return self.index(self.run(node[1]), self.run(node[2]))
        if kind == "call":
            return self.call(node[1], node[2])
        if kind == "un":
            v = self.run(node[2])
            return (not _truthy(v)) if node[1] == "!" else (-_num(v) if node[1] == "-" else _num(v))
        if kind == "cond":
            return self.run(node[2]) if _truthy(self.run(node[1])) else self.run(node[3])
        if kind == "bin":
            return self.binop(node[1], node[2], node[3])
        raise ExpressionError("unsupported expression")

    def var(self, name: str) -> Any:
        c = self.ctx
        if name == "$json":
            return c.current().get("json", {})
        if name == "$input":
            return _InputRef(c)
        if name == "$node":
            return _NodeIndexer(self)
        if name == "$":
            return _Fn(lambda n: _NodeRef(to_text(n), c.nodes(to_text(n)), c.index))
        if name == "$itemIndex":
            return c.index
        if name in ("$now", "$today"):
            return c.now if name == "$now" else c.now[:10]
        if name == "$execution":
            return c.execution
        if name == "$workflow":
            return c.workflow
        if name in _GLOBALS:
            return _GLOBALS[name]
        raise ExpressionError(f"unknown variable '{name}'")

    def member(self, obj: Any, name: str) -> Any:
        if name.startswith("_"):
            raise ExpressionError(f"cannot read '{name}'")
        if isinstance(obj, _NodeRef):
            if name in ("json", "item"):
                it = obj.linked()
                return it.get("json", {}) if name == "json" else it
            if name == "data":
                return obj.linked().get("json", {})
            if name in _ITEM_METHODS:
                return _item_method(obj.items, name)
            raise ExpressionError(f"nodes have no '{name}' (use .json, .item, .first(), .last(), .all())")
        if isinstance(obj, _InputRef):
            items = obj.ctx.items
            if name == "item":
                return obj.ctx.current()
            if name == "json":
                return obj.ctx.current().get("json", {})
            if name in _ITEM_METHODS:
                return _item_method(items, name)
            raise ExpressionError(f"$input has no '{name}'")
        if isinstance(obj, dict):
            if name in obj:
                return obj[name]
            if name in _DICT_METHODS:
                return _Fn(lambda *a, _n=name, _o=obj: _DICT_METHODS[_n](_o, *a))
            return None
        if isinstance(obj, (list, str)) and name == "length":
            return len(obj)
        table = {str: _STR_METHODS, list: _LIST_METHODS, int: _NUM_METHODS, float: _NUM_METHODS}.get(type(obj))
        if table and name in table and not isinstance(obj, bool):
            return _Fn(lambda *a, _t=table[name], _o=obj: _t(_o, *a))
        if obj is None:
            return None
        raise ExpressionError(f"'{name}' is not available here")

    def index(self, obj: Any, key: Any) -> Any:
        if isinstance(obj, _NodeIndexer):
            return obj.get(to_text(key))
        if isinstance(obj, dict):
            k = to_text(key)
            if k.startswith("_"):
                raise ExpressionError(f"cannot read '{k}'")
            return obj.get(k)
        if isinstance(obj, (list, str)):
            if isinstance(key, (int, float)) and not isinstance(key, bool):
                i = int(key)
                return obj[i] if -len(obj) <= i < len(obj) else None
            return None
        return None

    def call(self, fn_node, arg_nodes) -> Any:
        fn = self.run(fn_node)
        if not isinstance(fn, _Fn):
            raise ExpressionError("that is not a function")
        args = [self.run(a) for a in arg_nodes]
        try:
            out = fn.fn(*args)
        except ExpressionError:
            raise
        except (TypeError, ValueError, IndexError, KeyError, json.JSONDecodeError) as exc:
            raise ExpressionError(f"function call failed: {type(exc).__name__}") from exc
        if isinstance(out, str) and len(out) > MAX_STRING:
            raise ExpressionError("result is too large")
        return out

    def binop(self, op: str, a_node, b_node) -> Any:
        if op == "&&":
            a = self.run(a_node)
            return self.run(b_node) if _truthy(a) else a
        if op == "||":
            a = self.run(a_node)
            return a if _truthy(a) else self.run(b_node)
        if op == "??":
            a = self.run(a_node)
            return a if a is not None else self.run(b_node)
        a, b = self.run(a_node), self.run(b_node)
        if op == "+":
            if isinstance(a, str) or isinstance(b, str) or isinstance(a, (list, dict)) or isinstance(b, (list, dict)):
                out = to_text(a) + to_text(b)
                if len(out) > MAX_STRING:
                    raise ExpressionError("result is too large")
                return out
            return _num(a) + _num(b)
        if op == "-":
            return _num(a) - _num(b)
        if op == "*":
            return _num(a) * _num(b)
        if op == "/":
            d = _num(b)
            return math.nan if d == 0 else _num(a) / d
        if op == "%":
            d = _num(b)
            return math.nan if d == 0 else math.fmod(_num(a), d)
        if op == "===":
            return _strict_eq(a, b)
        if op == "!==":
            return not _strict_eq(a, b)
        if op == "==":
            return _loose_eq(a, b)
        if op == "!=":
            return not _loose_eq(a, b)
        if isinstance(a, str) and isinstance(b, str):
            x, y = a, b
        else:
            x, y = _num(a), _num(b)
        return {"<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y}[op]


class _NodeIndexer:
    def __init__(self, ev: _Eval):
        self.ev = ev

    def get(self, name: str) -> _NodeRef:
        return _NodeRef(name, self.ev.ctx.nodes(name), self.ev.ctx.index)


# ------------------------------------------------------------------------------------------------ public API

_PAIR = re.compile(r"\{\{(.*?)\}\}", re.S)
_cache: dict[str, Any] = {}


def evaluate_expression(src: str, ctx: ExprContext) -> Any:
    """Evaluate the inside of one {{ }}."""
    ast = _cache.get(src)
    if ast is None:
        ast = parse(src.strip())
        if len(_cache) < 500:
            _cache[src] = ast
    return _clean(_Eval(ctx).run(ast))


def _clean(v: Any) -> Any:
    """Wrapper objects never escape: they become plain data."""
    if isinstance(v, _NodeRef):
        return v.linked()
    if isinstance(v, (_Fn, _InputRef, _NodeIndexer)):
        raise ExpressionError("the expression returns a function or reference; add .json or call it")
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return int(v)
    return v


def evaluate_template(text: str, ctx: ExprContext) -> Any:
    """'{{ expr }}' alone keeps the value's type; text mixed with {{ }} becomes a string."""
    if "{{" not in text:
        return text
    whole = _PAIR.fullmatch(text.strip())
    if whole and text.strip().count("{{") == 1:
        return evaluate_expression(whole.group(1), ctx)
    try:
        return _PAIR.sub(lambda m: to_text(evaluate_expression(m.group(1), ctx)), text)
    except ExpressionError:
        raise


def resolve(value: Any, ctx: ExprContext, depth: int = 0) -> Any:
    """Evaluate every {{ }} inside a parameter value (dicts and lists are walked)."""
    if depth > 30:
        raise ExpressionError("parameter is nested too deeply")
    if isinstance(value, str):
        return evaluate_template(value, ctx)
    if isinstance(value, dict):
        return {k: resolve(v, ctx, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, ctx, depth + 1) for v in value]
    return value


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
