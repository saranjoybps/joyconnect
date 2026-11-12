"use client";

import { useId } from "react";

export type Rule = {
  interval: "seconds" | "minutes" | "hours" | "days" | "weeks" | "months" | "cron";
  every?: number;
  minute?: number;
  hour?: number;
  weekdays?: number[];
  day_of_month?: number;
  expression?: string;
};
export type ScheduleParams = { timezone?: string; rules?: Rule[] };

const INTERVALS: Rule["interval"][] = ["seconds", "minutes", "hours", "days", "weeks", "months", "cron"];
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const INPUT = "rounded-md border border-neutral-300 bg-transparent px-2 py-1 text-sm dark:border-neutral-700";

function zones(): string[] {
  try {
    return (Intl as unknown as { supportedValuesOnly?: never; supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.("timeZone") ?? ["UTC"];
  } catch {
    return ["UTC"];
  }
}

export function summarize(rule: Rule): string {
  const n = rule.every ?? 1;
  const at = `${String(rule.hour ?? 0).padStart(2, "0")}:${String(rule.minute ?? 0).padStart(2, "0")}`;
  switch (rule.interval) {
    case "seconds":
    case "minutes":
      return `Every ${n} ${rule.interval}`;
    case "hours":
      return `Every ${n} hour${n === 1 ? "" : "s"} at minute ${rule.minute ?? 0}`;
    case "days":
      return `Every ${n} day${n === 1 ? "" : "s"} at ${at}`;
    case "weeks":
      return `${(rule.weekdays ?? [1]).map((d) => DAYS[d]).join(", ")} at ${at}${n > 1 ? ` (every ${n} weeks)` : ""}`;
    case "months":
      return `Day ${rule.day_of_month ?? 1} of every ${n === 1 ? "" : `${n} `}month at ${at}`;
    default:
      return `Cron ${rule.expression ?? ""}`;
  }
}

/** Form for the Schedule Trigger: time zone plus one or more rules. Saves the whole parameters on every change. */
export function ScheduleEditor({ value, onChange }: { value: ScheduleParams; onChange: (v: ScheduleParams) => void }) {
  const tzId = useId();
  const listId = useId();
  const rules = value.rules ?? [];
  const setRule = (i: number, patch: Partial<Rule>) =>
    onChange({ ...value, rules: rules.map((r, j) => (j === i ? { ...r, ...patch } : r)) });
  const num = (v: string) => (v.trim() === "" ? undefined : Number(v));

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <label htmlFor={tzId} className="text-xs font-medium">Time zone</label>
        <input
          id={tzId}
          list={listId}
          className={`${INPUT} w-full`}
          defaultValue={value.timezone ?? "UTC"}
          key={value.timezone ?? "UTC"}
          onBlur={(e) => e.target.value !== (value.timezone ?? "UTC") && onChange({ ...value, timezone: e.target.value || "UTC" })}
        />
        <datalist id={listId}>{zones().map((z) => <option key={z} value={z} />)}</datalist>
      </div>

      {rules.map((r, i) => (
        <fieldset key={i} className="space-y-2 rounded-md border border-neutral-200 p-2 dark:border-neutral-800">
          <legend className="px-1 text-xs font-medium">Rule {i + 1}</legend>
          <p className="text-xs text-neutral-600 dark:text-neutral-400">{summarize(r)}</p>
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-xs">
              Repeat{" "}
              <select
                aria-label={`Rule ${i + 1} interval`}
                className={INPUT}
                value={r.interval}
                onChange={(e) => setRule(i, { interval: e.target.value as Rule["interval"] })}
              >
                {INTERVALS.map((v) => (
                  <option key={v} value={v}>{v === "cron" ? "cron expression" : v}</option>
                ))}
              </select>
            </label>
            {r.interval !== "cron" && (
              <label className="text-xs">
                every{" "}
                <input
                  aria-label={`Rule ${i + 1} every`}
                  type="number"
                  min={1}
                  className={`${INPUT} w-20`}
                  defaultValue={r.every ?? 1}
                  key={`e${r.every}`}
                  onBlur={(e) => setRule(i, { every: num(e.target.value) ?? 1 })}
                />
              </label>
            )}
          </div>
          {["hours", "days", "weeks", "months"].includes(r.interval) && (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {r.interval !== "hours" && (
                <label>
                  at hour{" "}
                  <input aria-label={`Rule ${i + 1} hour`} type="number" min={0} max={23} className={`${INPUT} w-16`} defaultValue={r.hour ?? 0} key={`h${r.hour}`} onBlur={(e) => setRule(i, { hour: num(e.target.value) ?? 0 })} />
                </label>
              )}
              <label>
                minute{" "}
                <input aria-label={`Rule ${i + 1} minute`} type="number" min={0} max={59} className={`${INPUT} w-16`} defaultValue={r.minute ?? 0} key={`m${r.minute}`} onBlur={(e) => setRule(i, { minute: num(e.target.value) ?? 0 })} />
              </label>
              {r.interval === "months" && (
                <label>
                  day of month{" "}
                  <input aria-label={`Rule ${i + 1} day of month`} type="number" min={1} max={31} className={`${INPUT} w-16`} defaultValue={r.day_of_month ?? 1} key={`d${r.day_of_month}`} onBlur={(e) => setRule(i, { day_of_month: num(e.target.value) ?? 1 })} />
                </label>
              )}
            </div>
          )}
          {r.interval === "weeks" && (
            <div className="flex flex-wrap gap-2" role="group" aria-label={`Rule ${i + 1} weekdays`}>
              {DAYS.map((d, idx) => {
                const on = (r.weekdays ?? [1]).includes(idx);
                return (
                  <label key={d} className="flex items-center gap-1 text-xs">
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() => {
                        const cur = r.weekdays ?? [1];
                        const next = on ? cur.filter((x) => x !== idx) : [...cur, idx].sort();
                        if (next.length) setRule(i, { weekdays: next });
                      }}
                    />
                    {d}
                  </label>
                );
              })}
            </div>
          )}
          {r.interval === "cron" && (
            <label className="block text-xs">
              Cron expression (minute hour day month weekday)
              <input
                aria-label={`Rule ${i + 1} cron expression`}
                className={`${INPUT} mt-1 w-full font-mono`}
                placeholder="*/15 * * * *"
                defaultValue={r.expression ?? ""}
                key={`x${r.expression}`}
                onBlur={(e) => setRule(i, { expression: e.target.value })}
              />
            </label>
          )}
          {rules.length > 1 && (
            <button type="button" className="text-xs text-red-700 underline dark:text-red-400" onClick={() => onChange({ ...value, rules: rules.filter((_, j) => j !== i) })}>
              Remove rule
            </button>
          )}
        </fieldset>
      ))}
      <button type="button" className="text-xs underline" onClick={() => onChange({ ...value, rules: [...rules, { interval: "days", every: 1, hour: 9, minute: 0 }] })}>
        Add rule
      </button>
      <p className="text-xs text-neutral-600 dark:text-neutral-400">
        Schedules run the <strong>published</strong> version. The shortest interval is 10 seconds; runs missed while the worker was off are skipped.
      </p>
    </div>
  );
}
