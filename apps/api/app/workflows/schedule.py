"""Schedule Trigger timing, following n8n's documented intervals (docs.n8n.io, Schedule Trigger): every N
seconds, minutes, hours, days, weeks, months, or a cron expression (the sixth, optional, seconds field comes
first). Wall-clock rules are evaluated in the rule's time zone and returned in UTC.

Simplifications, written down in docs/decisions.md: "every N hours/days/weeks/months" fires on the calendar
units that are multiples of N (hours 0, N, 2N ...; days by day number; weeks by week number; months by month
number), not N units after the previous run; missed runs are discarded (n8n's default).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MIN_INTERVAL_SECONDS = 10
MAX_DAYS_AHEAD = 366 * 8
_MONTHS = {n: i for i, n in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}
_DAYS = {n: i for i, n in enumerate("SUN MON TUE WED THU FRI SAT".split())}


class ScheduleError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------ cron

def _field(spec: str, lo: int, hi: int, names: dict[str, int] | None = None) -> tuple[set[int], bool]:
    values: set[int] = set()
    star = spec.strip() in ("*", "?")
    for part in spec.split(","):
        part = part.strip()
        if not part:
            raise ScheduleError(f"empty value in '{spec}'")
        rng, _, step_s = part.partition("/")
        try:
            step = int(step_s) if step_s else 1
        except ValueError as exc:
            raise ScheduleError(f"bad step in '{part}'") from exc
        if step < 1:
            raise ScheduleError(f"step must be at least 1 in '{part}'")

        def num(tok: str) -> int:
            tok = tok.upper()
            if names and tok in names:
                return names[tok]
            try:
                return int(tok)
            except ValueError as exc:
                raise ScheduleError(f"'{tok}' is not a valid value") from exc

        if rng in ("*", "?"):
            a, b = lo, hi
        elif "-" in rng:
            x, y = rng.split("-", 1)
            a, b = num(x), num(y)
        else:
            a = num(rng)
            b = hi if step_s else a
        if not (lo <= a <= hi and lo <= b <= hi) or a > b:
            raise ScheduleError(f"'{part}' is outside {lo}-{hi}")
        values.update(range(a, b + 1, step))
    return values, star


class Cron:
    def __init__(self, expression: str):
        parts = expression.split()
        if len(parts) not in (5, 6):
            raise ScheduleError("a cron expression has 5 fields (minute hour day month weekday), or 6 with seconds first")
        if len(parts) == 5:
            parts = ["0"] + parts
        self.seconds, _ = _field(parts[0], 0, 59)
        self.minutes, _ = _field(parts[1], 0, 59)
        self.hours, _ = _field(parts[2], 0, 23)
        self.dom, self.dom_star = _field(parts[3], 1, 31)
        self.months, _ = _field(parts[4], 1, 12, _MONTHS)
        dow, self.dow_star = _field(parts[5], 0, 7, _DAYS)
        self.dow = {d % 7 for d in dow}
        self.times = sorted((h, m, s) for h in self.hours for m in self.minutes for s in self.seconds)

    def day_ok(self, d: date) -> bool:
        if d.month not in self.months:
            return False
        dom_ok, dow_ok = d.day in self.dom, ((d.weekday() + 1) % 7) in self.dow
        if self.dom_star and self.dow_star:
            return True
        if self.dom_star:
            return dow_ok
        if self.dow_star:
            return dom_ok
        return dom_ok or dow_ok          # standard cron: either matches when both are restricted


# ------------------------------------------------------------------------------------------------ rules

def _zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ScheduleError(f"unknown time zone '{name}'") from exc


def _next_by_day(after: datetime, tz: ZoneInfo, day_ok, times: list[tuple[int, int, int]]) -> datetime | None:
    local = after.astimezone(tz)
    start = local.date()
    for i in range(MAX_DAYS_AHEAD):
        day = start + timedelta(days=i)
        if not day_ok(day):
            continue
        for h, m, s in times:
            cand = datetime(day.year, day.month, day.day, h, m, s, tzinfo=tz)
            if cand > after:
                return cand.astimezone(timezone.utc)
    return None


def _int(rule: dict[str, Any], key: str, default: int, lo: int, hi: int) -> int:
    v = rule.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ScheduleError(f"'{key}' must be a whole number from {lo} to {hi}")
    return v


def next_for_rule(rule: dict[str, Any], after: datetime, tz: ZoneInfo) -> datetime | None:
    interval = rule.get("interval")
    every = _int(rule, "every", 1, 1, 1_000_000)
    if interval in ("seconds", "minutes"):
        seconds = every * (1 if interval == "seconds" else 60)
        if seconds < MIN_INTERVAL_SECONDS:
            raise ScheduleError(f"the shortest allowed interval is {MIN_INTERVAL_SECONDS} seconds")
        return after + timedelta(seconds=seconds)
    minute = _int(rule, "minute", 0, 0, 59)
    hour = _int(rule, "hour", 0, 0, 23)
    if interval == "hours":
        if every > 24:
            raise ScheduleError("every N hours: N can be at most 24 (use days for longer)")
        times = [(h, minute, 0) for h in range(24) if h % every == 0]
        return _next_by_day(after, tz, lambda d: True, times)
    if interval == "days":
        return _next_by_day(after, tz, lambda d: d.toordinal() % every == 0, [(hour, minute, 0)])
    if interval == "weeks":
        days = rule.get("weekdays", [1])
        if not isinstance(days, list) or not days or any(
                isinstance(x, bool) or not isinstance(x, int) or not 0 <= x <= 6 for x in days):
            raise ScheduleError("'weekdays' must be a list of numbers 0 (Sunday) to 6 (Saturday)")
        wanted = set(days)
        return _next_by_day(after, tz, lambda d: ((d.weekday() + 1) % 7) in wanted
                            and ((d.toordinal() + 6) // 7) % every == 0, [(hour, minute, 0)])
    if interval == "months":
        dom = _int(rule, "day_of_month", 1, 1, 31)
        return _next_by_day(after, tz, lambda d: d.day == dom and (d.year * 12 + d.month) % every == 0,
                            [(hour, minute, 0)])
    if interval == "cron":
        expr = rule.get("expression")
        if not isinstance(expr, str) or not expr.strip():
            raise ScheduleError("add a cron expression")
        cron = Cron(expr)
        nxt = _next_by_day(after, tz, cron.day_ok, cron.times)
        if nxt is not None and (nxt - after).total_seconds() < 0:
            return None
        return nxt
    raise ScheduleError(f"unknown interval '{interval}'")


def validate_config(config: dict[str, Any]) -> list[str]:
    """Errors for a Schedule Trigger's parameters (empty list = fine). Used when publishing."""
    errs: list[str] = []
    try:
        tz = _zone(config.get("timezone"))
    except ScheduleError as exc:
        return [str(exc)]
    rules = config.get("rules")
    if not isinstance(rules, list) or not rules:
        return ["add at least one schedule rule"]
    probe = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i, rule in enumerate(rules, 1):
        try:
            if not isinstance(rule, dict):
                raise ScheduleError("a rule must be an object")
            if next_for_rule(rule, probe, tz) is None:
                raise ScheduleError("this rule never fires")
        except ScheduleError as exc:
            errs.append(f"rule {i}: {exc}")
    return errs


def compute_next(config: dict[str, Any], after: datetime) -> datetime | None:
    """The next fire time strictly after `after` (UTC) across all rules, or None if no rule ever fires."""
    tz = _zone(config.get("timezone"))
    after = after if after.tzinfo else after.replace(tzinfo=timezone.utc)
    cands = [c for r in config.get("rules", []) if (c := next_for_rule(r, after, tz)) is not None]
    return min(cands) if cands else None
