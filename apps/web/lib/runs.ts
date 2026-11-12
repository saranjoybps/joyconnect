import { apiFetch } from "@/lib/api";

export type Run = {
  id: string;
  created_at: string | null;
  finished_at: string | null;
  connector: string;
  connector_name: string;
  tool: string;
  action: string;
  risk: "read" | "write" | "destructive" | null;
  status: "pending" | "approved" | "rejected" | "ok" | "error" | string;
  duration_ms: number | null;
  conversation_id: string | null;
  /** Tool arguments with secrets redacted. */
  input: unknown;
  /** Tool output with secrets redacted (or a short summary for older runs). */
  output: unknown;
};

export type RunsPage = {
  runs: Run[];
  total: number;
  connectors: { id: string; name: string }[];
  statuses: string[];
};

export type RunFilters = { connector?: string; status?: string; limit?: number; offset?: number };

export const runsApi = {
  list: (f: RunFilters = {}) => {
    const q = new URLSearchParams();
    if (f.connector) q.set("connector", f.connector);
    if (f.status) q.set("status", f.status);
    q.set("limit", String(f.limit ?? 50));
    if (f.offset) q.set("offset", String(f.offset));
    return apiFetch<RunsPage>(`/api/runs?${q.toString()}`);
  },
};

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function formatJson(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}
