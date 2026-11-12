"use client";

import { useEffect, useId, useState } from "react";
import { uiOf } from "@/lib/options";
import type { JsonSchema } from "@/lib/workflows";
import { OptionField, type OptionCtx } from "./OptionFields";

const INPUT =
  "w-full rounded-md border border-line-strong bg-field px-2 py-1.5 text-sm dark:border-neutral-700";

export function baseType(s: JsonSchema): string | undefined {
  if (Array.isArray(s.type)) return s.type.find((t) => t !== "null");
  return s.type;
}

/** Text typed into a number field: a number when it parses, else kept as text (it may be a {{ expression }}). */
export function parseScalar(text: string, type: string | undefined): unknown {
  const t = text.trim();
  if (t === "") return null;
  if ((type === "integer" || type === "number") && !t.includes("{{")) {
    const n = Number(t);
    if (Number.isFinite(n)) return n;
  }
  return text;
}

const LONG = /body|text|message|content|prompt|query|script|description|note/i;

export function ParamField({
  name,
  schema,
  value,
  required,
  onCommit,
  ctx,
}: {
  name: string;
  schema: JsonSchema;
  value: unknown;
  required: boolean;
  onCommit: (key: string, value: unknown) => void;
  /** App nodes: what the option loaders need (node type, chosen account, current parameters). */
  ctx?: OptionCtx;
}) {
  const id = useId();
  const ui = uiOf(schema);
  if (ui && ctx) {
    return (
      <OptionField name={name} label={name.replace(/_/g, " ")} required={required} hint={schema.description} spec={ui} value={value} ctx={ctx} onCommit={onCommit} />
    );
  }
  const type = baseType(schema);
  const label = name.replace(/_/g, " ");
  const hint = schema.description;

  const wrap = (control: React.ReactNode) => (
    <div className="space-y-1">
      <label htmlFor={id} className="text-xs font-medium capitalize">
        {label}
        {required && <span aria-hidden className="text-red-600"> *</span>}
      </label>
      {control}
      {hint && <p className="text-xs text-neutral-600 dark:text-neutral-400">{hint}</p>}
    </div>
  );

  if (schema.enum) {
    return wrap(
      <select
        id={id}
        className={INPUT}
        value={value == null ? "" : String(value)}
        onChange={(e) => onCommit(name, e.target.value === "" ? null : e.target.value)}
      >
        <option value="">{schema.default !== undefined ? `Default (${String(schema.default)})` : "Not set"}</option>
        {schema.enum.map((o) => (
          <option key={String(o)} value={String(o)}>
            {String(o)}
          </option>
        ))}
      </select>,
    );
  }
  if (type === "boolean") {
    return (
      <div className="flex items-center gap-2">
        <input
          id={id}
          type="checkbox"
          checked={value === undefined || value === null ? Boolean(schema.default) : Boolean(value)}
          onChange={(e) => onCommit(name, e.target.checked)}
        />
        <label htmlFor={id} className="text-xs font-medium capitalize">{label}</label>
      </div>
    );
  }
  if (type === "string" || type === "integer" || type === "number") {
    return (
      <TextField
        id={id}
        wrap={wrap}
        multiline={type === "string" && LONG.test(name)}
        value={value}
        placeholder={schema.default !== undefined ? String(schema.default) : undefined}
        onCommit={(text) => onCommit(name, parseScalar(text, type))}
      />
    );
  }
  return <JsonField id={id} wrap={wrap} value={value} onCommit={(v) => onCommit(name, v)} />;
}

function TextField({
  id,
  wrap,
  value,
  multiline,
  placeholder,
  onCommit,
}: {
  id: string;
  wrap: (c: React.ReactNode) => React.ReactNode;
  value: unknown;
  multiline: boolean;
  placeholder?: string;
  onCommit: (text: string) => void;
}) {
  const external = value == null ? "" : String(value);
  const [text, setText] = useState(external);
  useEffect(() => setText(external), [external]);
  const commit = () => text !== external && onCommit(text);
  return wrap(
    multiline ? (
      <textarea id={id} rows={3} className={`${INPUT} font-mono`} value={text} placeholder={placeholder} onChange={(e) => setText(e.target.value)} onBlur={commit} />
    ) : (
      <input id={id} className={INPUT} value={text} placeholder={placeholder} onChange={(e) => setText(e.target.value)} onBlur={commit} />
    ),
  );
}

function JsonField({
  id,
  wrap,
  value,
  onCommit,
}: {
  id: string;
  wrap: (c: React.ReactNode) => React.ReactNode;
  value: unknown;
  onCommit: (v: unknown) => void;
}) {
  const external = value === undefined || value === null ? "" : JSON.stringify(value, null, 2);
  const [text, setText] = useState(external);
  const [bad, setBad] = useState(false);
  useEffect(() => {
    setText(external);
    setBad(false);
  }, [external]);
  function commit() {
    if (text === external) return;
    if (text.trim() === "") return onCommit(null);
    try {
      const parsed = JSON.parse(text);
      setBad(false);
      onCommit(parsed);
    } catch {
      setBad(true);
    }
  }
  return wrap(
    <>
      <textarea
        id={id}
        rows={4}
        spellCheck={false}
        aria-invalid={bad}
        className={`${INPUT} font-mono text-xs ${bad ? "border-red-500" : ""}`}
        value={text}
        placeholder="JSON"
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
      />
      {bad && <p role="alert" className="text-xs text-red-700 dark:text-red-400">That is not valid JSON, so it was not saved.</p>}
    </>,
  );
}
