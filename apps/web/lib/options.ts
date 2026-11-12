import { ApiError, apiFetch } from "@/lib/api";
import type { JsonSchema, NodeType } from "@/lib/workflows";

/** How the canvas edits one parameter of an app node (the registry's `x-ui` hint). */
export type UiSpec = {
  kind: "locator" | "options" | "multi" | "columns" | "range";
  loader: string;
  depends_on?: string[];
  modes?: ("list" | "url" | "id")[];
  url_pattern?: string;
  output?: "array" | "object" | "json";
  empty_label?: string;
};

export type Option = { value: string | number; name: string; description?: string; url?: string };

export type OptionsResult = { options: Option[]; cached: boolean; loader: string; unresolved?: boolean; message?: string };

export type OptionsRequest = {
  parameter: string;
  connection_id: string;
  parameters: Record<string, unknown>;
  query?: string;
  refresh?: boolean;
};

export const OPTIONS_TTL_MS = 60_000;
const cache = new Map<string, { at: number; result: OptionsResult }>();

export function clearOptionsCache(): void {
  cache.clear();
}

export const isExpression = (v: unknown): boolean => typeof v === "string" && v.includes("{{");

export function uiOf(schema: JsonSchema): UiSpec | undefined {
  return (schema as { "x-ui"?: UiSpec })["x-ui"];
}

/** The parameters that must be cleared when `key` changes: everything that depends on it, directly or not. */
export function dependentsOf(props: Record<string, JsonSchema>, key: string): string[] {
  const out: string[] = [];
  const queue = [key];
  while (queue.length) {
    const parent = queue.shift()!;
    for (const [name, schema] of Object.entries(props)) {
      if (!out.includes(name) && uiOf(schema)?.depends_on?.includes(parent)) {
        out.push(name);
        queue.push(name);
      }
    }
  }
  return out;
}

/** The inputs that decide a list's content: the dependency values only, so unrelated edits do not reload it. */
export function dependencyKey(spec: UiSpec, parameters: Record<string, unknown>): string {
  return JSON.stringify((spec.depends_on ?? []).map((d) => parameters[d] ?? null));
}

export const optionsApi = {
  /** Loads a list. Results are cached for a minute per node type, account, inputs and query; `refresh` bypasses it. */
  async load(nodeType: string, req: OptionsRequest): Promise<OptionsResult> {
    const key = JSON.stringify([nodeType, req.connection_id, req.parameter, req.query ?? "", req.parameters]);
    const hit = cache.get(key);
    if (!req.refresh && hit && Date.now() - hit.at < OPTIONS_TTL_MS) return { ...hit.result, cached: true };
    const result = await apiFetch<OptionsResult>(`/api/nodes/${encodeURIComponent(nodeType)}/options`, {
      method: "POST",
      body: JSON.stringify(req),
    });
    cache.set(key, { at: Date.now(), result });
    return result;
  },
};

export type OptionsError = { code: string; message: string };

export function toOptionsError(e: unknown): OptionsError {
  if (e instanceof ApiError) return { code: String(e.detail.code ?? "error"), message: e.message };
  return { code: "error", message: "Could not load the list." };
}

/** A value pasted in "By URL" mode, reduced to the id with the connector's pattern; null if it does not match. */
export function idFromUrl(text: string, pattern: string | undefined): string | null {
  const t = text.trim();
  if (!t) return null;
  if (!pattern) return t;
  const m = new RegExp(pattern).exec(t);
  return m ? m[1] : null;
}

export type { NodeType };
