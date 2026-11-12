"""Conditions for IF, Switch and Filter, with the operators n8n documents per data type
(docs.n8n.io: If node, Switch node, Filter node): String, Number, Date & Time, Boolean, Array, Object;
combined with AND or OR (not mixed); options Ignore Case and Less Strict Type Validation."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

COMMON = ["exists", "not_exists", "is_empty", "is_not_empty"]
OPERATORS: dict[str, list[str]] = {
    "string": COMMON + ["equals", "not_equals", "contains", "not_contains", "starts_with", "not_starts_with",
                        "ends_with", "not_ends_with", "matches_regex", "not_matches_regex"],
    "number": COMMON + ["equals", "not_equals", "gt", "lt", "gte", "lte"],
    "datetime": COMMON + ["equals", "not_equals", "after", "before", "after_or_equal", "before_or_equal"],
    "boolean": ["exists", "not_exists", "is_true", "is_false", "equals", "not_equals"],
    "array": COMMON + ["contains", "not_contains", "length_equals", "length_not_equals", "length_gt", "length_lt",
                       "length_gte", "length_lte"],
    "object": COMMON,
}
NEGATIVE = {"not_equals", "not_contains", "not_starts_with", "not_ends_with", "not_matches_regex",
            "length_not_equals"}
MAX_REGEX_CHARS = 300
MAX_REGEX_INPUT = 20_000


class ConditionError(Exception):
    pass


def _coerce(value: Any, typ: str, loose: bool) -> Any:
    """Strict mode: the value must already have the type. Loose mode converts where it sensibly can."""
    if value is None:
        return None
    ok = {"string": isinstance(value, str),
          "number": isinstance(value, (int, float)) and not isinstance(value, bool),
          "boolean": isinstance(value, bool), "array": isinstance(value, list), "object": isinstance(value, dict),
          "datetime": isinstance(value, (str, int, float, datetime)) and not isinstance(value, bool)}[typ]
    if ok and typ != "datetime":
        return value
    if typ == "datetime":
        return _to_datetime(value)
    if not loose:
        raise ConditionError(f"wrong type: expected {typ} but got {type(value).__name__}; "
                             "turn on 'less strict type validation' to convert it")
    try:
        if typ == "string":
            return str(value)
        if typ == "number":
            return float(value)
        if typ == "boolean":
            if isinstance(value, str) and value.lower() in ("true", "false"):
                return value.lower() == "true"
            if isinstance(value, (int, float)):
                return bool(value)
    except (TypeError, ValueError):
        pass
    raise ConditionError(f"cannot convert {value!r} to {typ}")


def _to_datetime(v: Any) -> datetime:
    if isinstance(v, datetime):
        d = v
    elif isinstance(v, (int, float)):
        d = datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=timezone.utc)
    else:
        try:
            d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ConditionError(f"'{v}' is not a date-time (use ISO 8601)") from exc
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _regex(pattern: str, text: str, ignore_case: bool) -> bool:
    if len(pattern) > MAX_REGEX_CHARS:
        raise ConditionError("regex is too long")
    try:
        return re.search(pattern, text[:MAX_REGEX_INPUT], re.I if ignore_case else 0) is not None
    except re.error as exc:
        raise ConditionError(f"invalid regex: {exc}") from exc


def _compare(op: str, left: Any, right: Any, typ: str, ignore_case: bool) -> bool:
    if typ == "string" and ignore_case:
        left = left.lower() if isinstance(left, str) else left
        right = right.lower() if isinstance(right, str) else right
    if op in ("equals", "not_equals"):
        res = left == right
        return res if op == "equals" else not res
    if typ == "string":
        s = {"contains": lambda: right in left, "not_contains": lambda: right not in left,
             "starts_with": lambda: left.startswith(right), "not_starts_with": lambda: not left.startswith(right),
             "ends_with": lambda: left.endswith(right), "not_ends_with": lambda: not left.endswith(right)}
        if op in s:
            return s[op]()
        if op in ("matches_regex", "not_matches_regex"):
            hit = _regex(right, left, ignore_case)
            return hit if op == "matches_regex" else not hit
    if typ in ("number", "datetime"):
        ops: dict[str, Callable[[Any, Any], bool]] = {
            "gt": lambda a, b: a > b, "lt": lambda a, b: a < b, "gte": lambda a, b: a >= b,
            "lte": lambda a, b: a <= b, "after": lambda a, b: a > b, "before": lambda a, b: a < b,
            "after_or_equal": lambda a, b: a >= b, "before_or_equal": lambda a, b: a <= b}
        if op in ops:
            return ops[op](left, right)
    if typ == "array":
        if op in ("contains", "not_contains"):
            hit = right in left
            return hit if op == "contains" else not hit
        n = len(left)
        ln = {"length_equals": n == right, "length_not_equals": n != right, "length_gt": n > right,
              "length_lt": n < right, "length_gte": n >= right, "length_lte": n <= right}
        if op in ln:
            return ln[op]
    raise ConditionError(f"operator '{op}' does not apply to {typ}")


def check_one(cond: dict[str, Any], left: Any, right: Any, ignore_case: bool, loose: bool) -> bool:
    """`left` and `right` are already evaluated for the current item."""
    typ, op = cond.get("type"), cond.get("op")
    if typ not in OPERATORS:
        raise ConditionError(f"unknown data type '{typ}'")
    if op not in OPERATORS[typ]:
        raise ConditionError(f"operator '{op}' does not apply to {typ}")
    if op == "exists":
        return left is not None
    if op == "not_exists":
        return left is None
    if op == "is_empty":
        return _empty(left)
    if op == "is_not_empty":
        return not _empty(left)
    if op == "is_true":
        return _coerce(left, "boolean", loose) is True
    if op == "is_false":
        return _coerce(left, "boolean", loose) is False
    lv = _coerce(left, typ, loose)
    if typ == "array" and op in ("contains", "not_contains"):
        rv = right
    else:
        rv = _coerce(right, "number" if op.startswith("length_") else typ, loose)
    if lv is None:   # a missing value: negative operators are true, everything else false
        return op in NEGATIVE
    return _compare(op, lv, rv, typ, ignore_case)


def evaluate(conditions: dict[str, Any] | None, resolve: Callable[[Any], Any]) -> bool:
    """`resolve` evaluates the expressions inside a condition's left/right for the current item.
    An empty condition list is true."""
    conditions = conditions or {}
    items = conditions.get("items") or []
    if not items:
        return True
    ignore_case, loose = bool(conditions.get("ignore_case")), bool(conditions.get("loose_types"))
    results = (check_one(c, resolve(c.get("left")), resolve(c.get("right")), ignore_case, loose) for c in items)
    return all(results) if conditions.get("combinator", "and") == "and" else any(results)
