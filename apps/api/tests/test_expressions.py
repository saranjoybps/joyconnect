"""Expressions (safe sandbox) and conditions (n8n operators)."""

import pytest

from app.workflows import conditions
from app.workflows.expressions import ExprContext, ExpressionError, evaluate_expression, resolve


def ctx(**over):
    base = dict(
        items=[{"json": {"name": "Ada", "n": 5, "tags": ["a", "b"], "user": {"email": "ada@x.com"}, "zero": 0}},
               {"json": {"name": "Bob", "n": 9}}],
        index=0, nodes=lambda name: {"Lead": [{"json": {"email": "lead@x.com"}}, {"json": {"email": "second@x.com"}}],
                                     "Empty": []}.get(name),
        execution={"id": "ex1", "mode": "manual"}, workflow={"id": "w1", "name": "WF"},
        now="2026-11-12T10:00:00+00:00")
    base.update(over)
    return ExprContext(**base)


@pytest.mark.parametrize("expr,expected", [
    ("$json.name", "Ada"),
    ("$json.user.email", "ada@x.com"),
    ("$json.tags[1]", "b"),
    ("$json.tags.length", 2),
    ("$json.n * 2 + 1", 11),
    ("($json.n + 1) * 2", 12),
    ("10 / 4", 2.5),
    ("7 % 4", 3),
    ("-$json.n", -5),
    ("$json.n > 3 && $json.name === 'Ada'", True),
    ("$json.n < 3 || $json.n == '5'", True),
    ("!$json.zero", True),
    ("$json.missing ?? 'fallback'", "fallback"),
    ("$json.zero ?? 'fallback'", 0),
    ("$json.n > 3 ? 'big' : 'small'", "big"),
    ("$json.name.toUpperCase() + '!'", "ADA!"),
    ("$json.name.slice(0, 2)", "Ad"),
    ("$json.tags.join('-')", "a-b"),
    ("$json.name.includes('d')", True),
    ("'a,b,c'.split(',').length", 3),
    ("'x' + 1 + 2", "x12"),
    ("1 + 2 + 'x'", "3x"),
    ("(3.14159).toFixed(2)", "3.14"),
    ("Math.round(2.5)", 3),
    ("Math.max(1, 9, 4)", 9),
    ("JSON.stringify($json.tags)", '["a", "b"]'),
    ("$input.all().length", 2),
    ("$input.first().json.name", "Ada"),
    ("$input.last().json.name", "Bob"),
    ("$input.item.json.n", 5),
    ("$itemIndex", 0),
    ("$now", "2026-11-12T10:00:00+00:00"),
    ("$today", "2026-11-12"),
    ("$execution.id", "ex1"),
    ("$workflow.name", "WF"),
    ("$node['Lead'].json.email", "lead@x.com"),
    ('$node["Lead"].json.email', "lead@x.com"),
    ('$("Lead").first().json.email', "lead@x.com"),
    ('$("Lead").last().json.email', "second@x.com"),
    ('$("Lead").all().length', 2),
    ('$("Lead").item.json.email', "lead@x.com"),
])
def test_expression_values(expr, expected):
    assert evaluate_expression(expr, ctx()) == expected


def test_node_reference_follows_the_current_item_index():
    assert evaluate_expression('$node["Lead"].json.email', ctx(index=1)) == "second@x.com"


def test_whole_template_keeps_type_and_mixed_text_becomes_string():
    c = ctx()
    assert resolve("{{ $json.n }}", c) == 5
    assert resolve("{{ $json.tags }}", c) == ["a", "b"]
    assert resolve("  {{ $json.n > 1 }}  ", c) is True
    assert resolve("Hi {{ $json.name }}, n={{ $json.n }}", c) == "Hi Ada, n=5"
    assert resolve("a {{ $json.tags }} b", c) == 'a ["a", "b"] b'
    assert resolve("plain", c) == "plain"
    assert resolve({"x": ["{{ $json.name }}", 1], "y": {"z": "{{ 1 + 1 }}"}}, c) == {"x": ["Ada", 1], "y": {"z": 2}}


@pytest.mark.parametrize("expr", [
    "__import__('os').system('id')",
    "$json.__class__",
    "$json._private",
    "$json['__class__']",
    "open('/etc/passwd')",
    "eval('1')",
    "process.env.SECRET",
    "this",
    "(function(){})()",
    "$json.name.constructor('return 1')()",
    "unknownVar + 1",
    "$node['Nope'].json.x",
    "$('Nope').first()",
    "$json.name.notAMethod()",
    "$json.n.toFixed",                      # returns a function reference
    "1 +",
    "1 2",
    "'unterminated",
    "{{ nested }}",
    "$json.n @ 3",
])
def test_unsafe_or_invalid_expressions_are_errors(expr):
    with pytest.raises(ExpressionError):
        evaluate_expression(expr, ctx())


def test_limits_stop_runaway_expressions():
    with pytest.raises(ExpressionError, match="longer than"):
        evaluate_expression("1+" * 1500 + "1", ctx())
    with pytest.raises(ExpressionError, match="nested too deeply"):
        evaluate_expression("(" * 60 + "1" + ")" * 60, ctx())
    with pytest.raises(ExpressionError, match="too large"):
        evaluate_expression("'x'.repeat(1000).repeat(1000).repeat(1000)", ctx())


def test_missing_data_is_null_not_a_crash():
    c = ctx()
    assert evaluate_expression("$json.a.b.c", c) is None
    assert evaluate_expression("$json.tags[9]", c) is None
    assert evaluate_expression("$json.user.nope.deeper", c) is None
    assert evaluate_expression("$json.constructor", c) is None      # not a Python/JS attribute lookup


def test_python_objects_never_leak():
    class Boom:
        def __getattr__(self, name):
            raise AssertionError("attribute access on a Python object")

    c = ctx(items=[{"json": {"obj": Boom()}}])
    with pytest.raises(ExpressionError):
        evaluate_expression("$json.obj.anything", c)


# ------------------------------------------------------------------ conditions

def cond(left, typ, op, right=None):
    return {"left": left, "type": typ, "op": op, "right": right}


def check(*items, combinator="and", ignore_case=False, loose=False):
    return conditions.evaluate({"combinator": combinator, "ignore_case": ignore_case, "loose_types": loose,
                                "items": list(items)}, lambda v: v)


@pytest.mark.parametrize("c,expected", [
    (cond("Hello", "string", "equals", "Hello"), True),
    (cond("Hello", "string", "not_equals", "Hello"), False),
    (cond("Hello", "string", "contains", "ell"), True),
    (cond("Hello", "string", "not_contains", "zzz"), True),
    (cond("Hello", "string", "starts_with", "He"), True),
    (cond("Hello", "string", "ends_with", "lo"), True),
    (cond("Hello", "string", "not_starts_with", "He"), False),
    (cond("a1b2", "string", "matches_regex", r"\d\w\d"), True),
    (cond("abc", "string", "not_matches_regex", r"^\d+$"), True),
    (cond("", "string", "is_empty"), True),
    (cond("x", "string", "is_not_empty"), True),
    (cond(None, "string", "exists"), False),
    (cond(None, "string", "not_exists"), True),
    (cond(5, "number", "gt", 3), True),
    (cond(5, "number", "lte", 5), True),
    (cond(5, "number", "lt", 5), False),
    (cond(5, "number", "equals", 5), True),
    (cond("2026-02-01", "datetime", "after", "2026-01-01"), True),
    (cond("2026-02-01T00:00:00Z", "datetime", "before", "2026-01-01"), False),
    (cond("2026-01-01", "datetime", "equals", "2026-01-01T00:00:00+00:00"), True),
    (cond(True, "boolean", "is_true"), True),
    (cond(False, "boolean", "is_false"), True),
    (cond(True, "boolean", "equals", True), True),
    ([1, 2, 3] and cond([1, 2, 3], "array", "contains", 2), True),
    (cond([1, 2, 3], "array", "length_gt", 2), True),
    (cond([1, 2, 3], "array", "length_equals", 4), False),
    (cond([], "array", "is_empty"), True),
    (cond({"a": 1}, "object", "is_not_empty"), True),
    (cond({}, "object", "is_empty"), True),
])
def test_condition_operators(c, expected):
    assert check(c) is expected


def test_and_or_and_empty_conditions():
    t, f = cond(1, "number", "equals", 1), cond(1, "number", "equals", 2)
    assert check(t, f) is False
    assert check(t, f, combinator="or") is True
    assert conditions.evaluate({"items": []}, lambda v: v) is True
    assert conditions.evaluate(None, lambda v: v) is True


def test_ignore_case_and_loose_types():
    assert check(cond("HELLO", "string", "equals", "hello")) is False
    assert check(cond("HELLO", "string", "equals", "hello"), ignore_case=True) is True
    assert check(cond("HeLLo", "string", "matches_regex", "^hello$"), ignore_case=True) is True
    with pytest.raises(conditions.ConditionError, match="wrong type"):
        check(cond("5", "number", "gt", 3))
    assert check(cond("5", "number", "gt", 3), loose=True) is True
    assert check(cond(5, "string", "equals", "5"), loose=True) is True
    assert check(cond("true", "boolean", "is_true"), loose=True) is True
    with pytest.raises(conditions.ConditionError, match="cannot convert"):
        check(cond("abc", "number", "gt", 3), loose=True)


def test_missing_values_and_bad_operators():
    assert check(cond(None, "string", "equals", "x")) is False
    assert check(cond(None, "string", "not_equals", "x")) is True
    assert check(cond(None, "number", "gt", 1)) is False
    with pytest.raises(conditions.ConditionError, match="does not apply"):
        check(cond("a", "string", "gt", 1))
    with pytest.raises(conditions.ConditionError, match="unknown data type"):
        check(cond("a", "color", "equals", "x"))
    with pytest.raises(conditions.ConditionError, match="regex"):
        check(cond("a", "string", "matches_regex", "("))
    with pytest.raises(conditions.ConditionError, match="not a date-time"):
        check(cond("yesterday-ish", "datetime", "after", "2026-01-01"))
