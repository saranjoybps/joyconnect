"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  dependencyKey, idFromUrl, isExpression, optionsApi, toOptionsError, type Option, type OptionsError, type UiSpec,
} from "@/lib/options";

const INPUT =
  "w-full rounded-lg border border-line-strong bg-field px-2 py-1.5 text-sm";

export type OptionCtx = { nodeType: string; connectionId: string | null; parameters: Record<string, unknown> };

type ListState = { status: "idle" | "loading" | "ready" | "error"; options: Option[]; error?: OptionsError; note?: string };

function missingDependency(spec: UiSpec, parameters: Record<string, unknown>): string | null {
  const dep = (spec.depends_on ?? []).find((d) => parameters[d] == null || parameters[d] === "");
  return dep ?? null;
}

/** Loads the choices for one parameter: re-runs when the account, the parent values or the search text change. */
function useOptionList(ctx: OptionCtx, parameter: string, spec: UiSpec, query = "") {
  const [state, setState] = useState<ListState>({ status: "idle", options: [] });
  const seq = useRef(0);
  const params = useRef(ctx.parameters);
  params.current = ctx.parameters;
  const blocked = missingDependency(spec, ctx.parameters);
  const depKey = dependencyKey(spec, ctx.parameters);

  const load = useCallback(
    async (refresh: boolean) => {
      const n = ++seq.current;
      if (!ctx.connectionId || blocked) {
        setState({ status: "idle", options: [] });
        return;
      }
      setState((s) => ({ ...s, status: "loading", error: undefined }));
      try {
        const r = await optionsApi.load(ctx.nodeType, {
          parameter, connection_id: ctx.connectionId, parameters: params.current, query: query || undefined, refresh,
        });
        if (n === seq.current) setState({ status: "ready", options: r.options, note: r.unresolved ? r.message : undefined });
      } catch (e) {
        if (n === seq.current) setState({ status: "error", options: [], error: toOptionsError(e) });
      }
    },
    // depKey stands in for the dependency values (params is read through a ref).
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ctx.nodeType, ctx.connectionId, parameter, query, depKey, blocked],
  );

  useEffect(() => {
    void load(false);
  }, [load]);
  return { ...state, blocked, reload: () => load(true) };
}

function Status({
  list, connectionId, label,
}: {
  list: ReturnType<typeof useOptionList>;
  connectionId: string | null;
  label: string;
}) {
  if (!connectionId) return <p className="text-xs text-m-muted">Choose an account first.</p>;
  if (list.blocked) {
    return <p className="text-xs text-m-muted">Choose “{list.blocked.replace(/_/g, " ")}” first.</p>;
  }
  if (list.status === "loading") return <p role="status" className="text-xs text-m-muted">Loading {label}…</p>;
  if (list.status === "error" && list.error) {
    return (
      <div role="alert" className="space-y-1 text-xs text-m-bad">
        <p>{list.error.message}</p>
        {list.error.code === "reconnect" ? (
          <Link href="/connections" className="inline-block rounded-full bg-m-ink px-3 py-1 font-medium text-m-ink-fg">Reconnect</Link>
        ) : (
          <button type="button" className="underline" onClick={() => void list.reload()}>Try again</button>
        )}
      </div>
    );
  }
  if (list.status === "ready" && list.note) return <p className="text-xs text-m-muted">{list.note}</p>;
  if (list.status === "ready" && list.options.length === 0) {
    return <p className="text-xs text-m-muted">Nothing found in this account.</p>;
  }
  return null;
}

function RefreshButton({ list, label }: { list: ReturnType<typeof useOptionList>; label: string }) {
  return (
    <button
      type="button"
      aria-label={`Refresh ${label}`}
      title={`Refresh ${label}`}
      disabled={list.status === "loading" || list.status === "idle"}
      onClick={() => void list.reload()}
      className="rounded-lg border border-m-line-strong px-2 text-sm disabled:opacity-40"
    >
      <span aria-hidden>↻</span>
    </button>
  );
}

/** The options plus the saved value when it is not in the list (so a saved choice never silently disappears). */
function withCurrent(options: Option[], value: unknown): Option[] {
  if (value == null || value === "" || isExpression(value)) return options;
  return options.some((o) => String(o.value) === String(value))
    ? options
    : [{ value: value as string, name: String(value), description: "saved value" }, ...options];
}

type FieldProps = {
  name: string;
  label: string;
  required: boolean;
  hint?: string;
  spec: UiSpec;
  value: unknown;
  ctx: OptionCtx;
  onCommit: (key: string, value: unknown) => void;
};

function Frame({ id, label, required, hint, children }: { id: string; label: string; required: boolean; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-xs font-medium capitalize">
        {label}
        {required && <span aria-hidden className="text-m-bad"> *</span>}
      </label>
      {children}
      {hint && <p className="text-xs text-m-muted">{hint}</p>}
    </div>
  );
}

/** Text that may be an expression, committed on blur. */
function ExprInput({ id, value, onCommit, placeholder }: { id: string; value: unknown; onCommit: (v: string) => void; placeholder?: string }) {
  const external = value == null ? "" : String(value);
  const [text, setText] = useState(external);
  useEffect(() => setText(external), [external]);
  return (
    <input
      id={id}
      className={INPUT}
      value={text}
      placeholder={placeholder}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => text !== external && onCommit(text)}
    />
  );
}

// ---------------------------------------------------------------------------------------------- dropdown

export function OptionsSelect(p: FieldProps) {
  const id = useId();
  const list = useOptionList(p.ctx, p.name, p.spec);
  const [expr, setExpr] = useState(isExpression(p.value));
  const options = withCurrent(list.options, p.value);
  return (
    <Frame id={id} label={p.label} required={p.required} hint={p.hint}>
      <div className="flex gap-1">
        {expr ? (
          <ExprInput id={id} value={p.value} placeholder="{{ $json.value }}" onCommit={(v) => p.onCommit(p.name, v === "" ? null : v)} />
        ) : (
          <select
            id={id}
            className={INPUT}
            value={p.value == null ? "" : String(p.value)}
            disabled={!p.ctx.connectionId || !!list.blocked}
            onChange={(e) => {
              const o = options.find((x) => String(x.value) === e.target.value);
              p.onCommit(p.name, o ? o.value : null);
            }}
          >
            <option value="">{p.spec.empty_label ?? (list.status === "loading" ? "Loading…" : "Choose…")}</option>
            {options.map((o) => (
              <option key={String(o.value)} value={String(o.value)}>
                {o.name}{o.description ? ` · ${o.description}` : ""}
              </option>
            ))}
          </select>
        )}
        {!expr && <RefreshButton list={list} label={p.label} />}
        <button type="button" className="rounded-lg border border-m-line-strong px-2 text-xs" aria-pressed={expr} onClick={() => setExpr(!expr)}>
          Expression
        </button>
      </div>
      {!expr && <Status list={list} connectionId={p.ctx.connectionId} label={p.label} />}
    </Frame>
  );
}

// ---------------------------------------------------------------------------------------------- multi-select

export function MultiSelect(p: FieldProps) {
  const id = useId();
  const list = useOptionList(p.ctx, p.name, p.spec);
  const chosen = Array.isArray(p.value) ? (p.value as unknown[]).map(String) : [];
  const toggle = (v: string, on: boolean) => {
    const next = on ? [...chosen, v] : chosen.filter((c) => c !== v);
    p.onCommit(p.name, next.length ? next : null);
  };
  return (
    <Frame id={id} label={p.label} required={p.required} hint={p.hint}>
      <div id={id} role="group" aria-label={p.label} className="max-h-40 space-y-1 overflow-y-auto rounded-lg border border-m-line-strong p-2">
        {list.options.map((o) => (
          <label key={String(o.value)} className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={chosen.includes(String(o.value))} onChange={(e) => toggle(String(o.value), e.target.checked)} />
            {o.name}
          </label>
        ))}
        {list.options.length === 0 && <p className="text-xs text-m-muted">{list.status === "loading" ? "Loading…" : "No choices yet."}</p>}
      </div>
      <div className="flex items-center gap-2">
        <RefreshButton list={list} label={p.label} />
        <span className="text-xs text-m-muted">{chosen.length ? `${chosen.length} selected` : "None selected"}</span>
      </div>
      <Status list={list} connectionId={p.ctx.connectionId} label={p.label} />
    </Frame>
  );
}

// ---------------------------------------------------------------------------------------------- resource locator

type Mode = "list" | "url" | "id";
const MODE_LABEL: Record<Mode, string> = { list: "From list", url: "By URL", id: "By ID" };

export function ResourceLocator(p: FieldProps) {
  const id = useId();
  const modes = p.spec.modes ?? ["list", "id"];
  const [mode, setMode] = useState<Mode>(isExpression(p.value) ? "id" : "list");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [urlText, setUrlText] = useState("");
  const [urlBad, setUrlBad] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);
  const list = useOptionList(p.ctx, p.name, p.spec, mode === "list" ? query : "");
  const needle = search.trim().toLowerCase();
  const options = withCurrent(list.options, p.value).filter((o) => !needle || o.name.toLowerCase().includes(needle) || String(o.value) === p.value);

  function commitUrl() {
    if (urlText.trim() === "") return;
    const found = idFromUrl(urlText, p.spec.url_pattern);
    setUrlBad(found === null);
    if (found !== null) p.onCommit(p.name, found);
  }

  return (
    <Frame id={id} label={p.label} required={p.required} hint={p.hint}>
      <div role="group" aria-label={`${p.label} source`} className="flex gap-1">
        {modes.map((m) => (
          <button
            key={m}
            type="button"
            aria-pressed={mode === m}
            onClick={() => setMode(m)}
            className={`rounded-md border px-2 py-0.5 text-xs ${mode === m ? "border-m-ink bg-m-ink text-m-ink-fg" : "border-line-strong"}`}
          >
            {MODE_LABEL[m]}
          </button>
        ))}
      </div>
      {mode === "list" && (
        <>
          <div className="flex gap-1">
            <input
              aria-label={`Search ${p.label}`}
              className={`${INPUT} max-w-28`}
              placeholder="Search…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <select
              id={id}
              className={INPUT}
              value={p.value == null || isExpression(p.value) ? "" : String(p.value)}
              disabled={!p.ctx.connectionId}
              onChange={(e) => {
                const o = options.find((x) => String(x.value) === e.target.value);
                p.onCommit(p.name, o ? o.value : null);
              }}
            >
              <option value="">{list.status === "loading" ? "Loading…" : "Choose…"}</option>
              {options.map((o) => (
                <option key={String(o.value)} value={String(o.value)}>
                  {o.name}{o.description ? ` · ${o.description}` : ""}
                </option>
              ))}
            </select>
            <RefreshButton list={list} label={p.label} />
          </div>
          <Status list={list} connectionId={p.ctx.connectionId} label={p.label} />
        </>
      )}
      {mode === "url" && (
        <>
          <input
            id={id}
            className={INPUT}
            placeholder="Paste the link"
            value={urlText}
            aria-invalid={urlBad}
            onChange={(e) => setUrlText(e.target.value)}
            onBlur={commitUrl}
            onKeyDown={(e) => e.key === "Enter" && commitUrl()}
          />
          {urlBad && <p role="alert" className="text-xs text-m-bad">That link does not look right, so nothing was changed.</p>}
          {!urlBad && p.value != null && p.value !== "" && <p className="text-xs text-m-muted">ID: <code>{String(p.value)}</code></p>}
        </>
      )}
      {mode === "id" && (
        <ExprInput id={id} value={p.value} placeholder="ID or {{ expression }}" onCommit={(v) => p.onCommit(p.name, v.trim() === "" ? null : v.trim())} />
      )}
    </Frame>
  );
}

// ---------------------------------------------------------------------------------------------- sheet range (tab + cells)

export function splitRange(value: string): { tab: string; cells: string } {
  if (!value) return { tab: "", cells: "" };
  const i = value.lastIndexOf("!");
  const rawTab = i >= 0 ? value.slice(0, i) : value;
  const cells = i >= 0 ? value.slice(i + 1) : "";
  const tab = rawTab.startsWith("'") && rawTab.endsWith("'") && rawTab.length >= 2 ? rawTab.slice(1, -1).replace(/''/g, "'") : rawTab;
  return { tab, cells };
}

export function joinRange(tab: string, cells: string): string {
  if (!tab) return cells;
  const q = /^[A-Za-z_][A-Za-z0-9_]*$/.test(tab) ? tab : `'${tab.replace(/'/g, "''")}'`;
  return cells.trim() ? `${q}!${cells.trim()}` : q;
}

export function RangeField(p: FieldProps) {
  const id = useId();
  const list = useOptionList(p.ctx, p.name, p.spec);
  const text = p.value == null ? "" : String(p.value);
  const { tab, cells } = splitRange(text);
  const [expr, setExpr] = useState(isExpression(p.value));
  const options = withCurrent(list.options, tab);
  return (
    <Frame id={id} label={p.label} required={p.required} hint={p.hint}>
      {expr ? (
        <ExprInput id={id} value={p.value} placeholder="Sheet1!A:Z or {{ expression }}" onCommit={(v) => p.onCommit(p.name, v === "" ? null : v)} />
      ) : (
        <div className="flex gap-1">
          <select
            id={id}
            aria-label="Tab"
            className={INPUT}
            value={tab}
            disabled={!p.ctx.connectionId || !!list.blocked}
            onChange={(e) => p.onCommit(p.name, e.target.value ? joinRange(e.target.value, cells) : null)}
          >
            <option value="">{list.status === "loading" ? "Loading…" : "Choose a tab…"}</option>
            {options.map((o) => <option key={String(o.value)} value={String(o.value)}>{o.name}{o.description ? ` · ${o.description}` : ""}</option>)}
          </select>
          <CellsInput value={cells} disabled={!tab} onCommit={(c) => p.onCommit(p.name, joinRange(tab, c))} />
          <RefreshButton list={list} label={p.label} />
        </div>
      )}
      <button type="button" aria-pressed={expr} className="text-xs underline" onClick={() => setExpr(!expr)}>
        {expr ? "Pick a tab" : "Expression"}
      </button>
      {!expr && <Status list={list} connectionId={p.ctx.connectionId} label="tabs" />}
    </Frame>
  );
}

function CellsInput({ value, disabled, onCommit }: { value: string; disabled: boolean; onCommit: (v: string) => void }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <input
      aria-label="Cells"
      className={`${INPUT} max-w-24`}
      placeholder="A:Z"
      disabled={disabled}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => text !== value && onCommit(text)}
    />
  );
}

// ---------------------------------------------------------------------------------------------- key-value column mapper

function parseCells(value: unknown, options: Option[], output: UiSpec["output"]): string[] {
  if (output === "array") return options.map((_, i) => (Array.isArray(value) && value[i] != null ? String(value[i]) : ""));
  let obj: Record<string, unknown> = {};
  if (output === "json" && typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (parsed && typeof parsed === "object") obj = parsed as Record<string, unknown>;
    } catch {
      /* not JSON yet */
    }
  } else if (value && typeof value === "object" && !Array.isArray(value)) obj = value as Record<string, unknown>;
  return options.map((o) => (obj[String(o.value)] != null ? String(obj[String(o.value)]) : ""));
}

export function buildMapped(cells: string[], options: Option[], output: UiSpec["output"]): unknown {
  if (output === "array") return cells;
  const obj: Record<string, string> = {};
  options.forEach((o, i) => {
    if (cells[i]?.trim()) obj[String(o.value)] = cells[i];
  });
  if (Object.keys(obj).length === 0) return null;
  return output === "json" ? JSON.stringify(obj) : obj;
}

export function ColumnMapper(p: FieldProps) {
  const id = useId();
  const list = useOptionList(p.ctx, p.name, p.spec);
  const output = p.spec.output ?? "array";
  const options = list.options;
  const external = JSON.stringify(parseCells(p.value, options, output));
  const [cells, setCells] = useState<string[]>(() => parseCells(p.value, options, output));
  useEffect(() => setCells(JSON.parse(external) as string[]), [external]);
  const commit = (next: string[]) => {
    if (JSON.stringify(next) !== external) p.onCommit(p.name, buildMapped(next, options, output));
  };
  const autoMap = () => {
    const next = options.map((o) => `{{ $json[${JSON.stringify(String(o.value))}] }}`);
    setCells(next);
    commit(next);
  };
  return (
    <Frame id={id} label={p.label} required={p.required} hint={p.hint}>
      <div id={id} role="group" aria-label={`${p.label} columns`} className="space-y-1 rounded-lg border border-m-line p-2 ">
        {options.map((o, i) => (
          <div key={`${i}-${String(o.value)}`} className="grid grid-cols-[7rem_1fr] items-center gap-2">
            <label htmlFor={`${id}-${i}`} className="truncate text-xs" title={o.description ? `${o.name} (${o.description})` : o.name}>{o.name}</label>
            <input
              id={`${id}-${i}`}
              className={INPUT}
              placeholder="value or {{ expression }}"
              value={cells[i] ?? ""}
              onChange={(e) => setCells(cells.map((c, j) => (j === i ? e.target.value : c)))}
              onBlur={() => commit(cells)}
            />
          </div>
        ))}
        {options.length === 0 && (
          <p className="text-xs text-m-muted">
            {list.status === "loading" ? "Loading columns…" : "No columns yet."}
          </p>
        )}
      </div>
      <div className="flex items-center gap-2">
        <button type="button" disabled={options.length === 0} onClick={autoMap} className="rounded-lg border border-m-line-strong px-2 py-0.5 text-xs disabled:opacity-40">
          Auto-map from input
        </button>
        <button
          type="button"
          disabled={options.length === 0}
          onClick={() => {
            const empty = options.map(() => "");
            setCells(empty);
            commit(empty);
          }}
          className="text-xs underline disabled:opacity-40"
        >
          Clear
        </button>
        <RefreshButton list={list} label="columns" />
      </div>
      <Status list={list} connectionId={p.ctx.connectionId} label="columns" />
    </Frame>
  );
}

export function OptionField(p: FieldProps) {
  switch (p.spec.kind) {
    case "locator": return <ResourceLocator {...p} />;
    case "multi": return <MultiSelect {...p} />;
    case "range": return <RangeField {...p} />;
    case "columns": return <ColumnMapper {...p} />;
    default: return <OptionsSelect {...p} />;
  }
}
