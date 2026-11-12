"use client";

import { ApiError, apiFetch } from "@/lib/api";
import { env } from "@/lib/env";
import { readSse, type SseEvent } from "@/lib/sse";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import type { Risk } from "@/lib/connections";
import type { ChatMode } from "@/lib/modes";

export type ApprovalPreview = {
  approval_id: string;
  tool_call_id: string;
  conversation_id: string;
  tool: string;
  connector: string;
  connector_name: string;
  account: string | null;
  action: string;
  description: string;
  risk: Risk;
  args: Record<string, unknown>;
};

/** Validated record of one tool call, built by the API from the audited tool result. */
export type Action = {
  id: string;
  connector: string;
  connector_name: string;
  tool: string;
  label: string;
  ok: boolean;
  result: string;
  link: string | null;
  error_kind: "auth" | "scope" | "server" | "other" | null;
};

export type ChatItem =
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string }
  | {
    kind: "tool"; id: string; tool: string; label: string; status: "running" | "ok" | "error";
    summary?: string | null; action?: Action | null;
    connector?: string; input?: Record<string, unknown> | null; output?: string | null; duration_ms?: number | null;
  }
  | { kind: "memory"; count: number }
  | { kind: "approval"; approval: ApprovalPreview; state: "pending" | "submitting" | "approved" | "rejected" }
  | { kind: "error"; text: string };

export type Conversation = { id: string; title: string | null; created_at: string; preview?: string };

export type ConversationDetail = {
  id: string;
  title: string | null;
  items: (
    | { kind: "user" | "assistant"; text: string }
    | { kind: "tool"; id: string; tool: string; ok: boolean; summary: string | null; action?: Action | null }
  )[];
  pending_approvals: ApprovalPreview[];
  mode?: { command: string; kind: string; connector: string | null };
};

/** Fallback label from a tool name: 'google_sheets__append_row' -> 'Append row'. */
export function labelFor(tool: string): string {
  const action = (tool.split("__")[1] ?? tool).replace(/_/g, " ");
  return action.charAt(0).toUpperCase() + action.slice(1);
}

export function itemsFromDetail(detail: ConversationDetail): ChatItem[] {
  const items: ChatItem[] = detail.items.map((i) =>
    i.kind === "tool"
      ? { kind: "tool", id: i.id, tool: i.tool, label: labelFor(i.tool), status: i.ok ? "ok" : "error", summary: i.summary, action: i.action ?? null }
      : { kind: i.kind, text: i.text },
  );
  for (const a of detail.pending_approvals) items.push({ kind: "approval", approval: a, state: "pending" });
  return items;
}

/** Pure reducer: apply one agent SSE event to the visible transcript. */
export function applyEvent(items: ChatItem[], ev: SseEvent): ChatItem[] {
  const d = (ev.data ?? {}) as Record<string, unknown>;
  switch (ev.event) {
    case "token": {
      const last = items[items.length - 1];
      if (last?.kind === "assistant") {
        return [...items.slice(0, -1), { ...last, text: last.text + String(d.text ?? "") }];
      }
      return [...items, { kind: "assistant", text: String(d.text ?? "") }];
    }
    case "tool_call":
      return [...items, {
        kind: "tool", id: String(d.id), tool: String(d.tool),
        label: `${d.connector_name ?? ""} · ${d.label ?? labelFor(String(d.tool))}`.replace(/^ · /, ""),
        status: "running",
        connector: d.connector ? String(d.connector) : undefined,
        input: (d.input as Record<string, unknown> | undefined) ?? null,
      }];
    case "tool_result": {
      const idx = items.findIndex((i) => i.kind === "tool" && i.id === d.id);
      const status = d.ok ? "ok" : "error";
      const summary = d.ok ? null : String(d.summary ?? "");
      const action = (d.action as Action | null | undefined) ?? null;
      const output = typeof d.output === "string" ? d.output : null;
      const duration_ms = typeof d.duration_ms === "number" ? d.duration_ms : null;
      if (idx === -1) {
        return [...items, { kind: "tool", id: String(d.id), tool: String(d.tool), label: labelFor(String(d.tool)), status, summary, action, output, duration_ms }];
      }
      const next = [...items];
      next[idx] = { ...(next[idx] as Extract<ChatItem, { kind: "tool" }>), status, summary, action, output, duration_ms };
      return next;
    }
    case "approval_required":
      return [...items, { kind: "approval", approval: d as unknown as ApprovalPreview, state: "pending" }];
    case "memory":
      return [...items, { kind: "memory", count: Number(d.count ?? 0) }];
    case "error":
      return [...items, { kind: "error", text: String(d.message ?? "Something went wrong.") }];
    default:
      return items;
  }
}

async function token(): Promise<string | null> {
  const { data } = await getSupabaseBrowserClient().auth.getSession();
  return data.session?.access_token ?? null;
}

async function* streamPost(path: string, body: unknown, signal?: AbortSignal): AsyncGenerator<SseEvent> {
  const t = await token();
  const resp = await fetch(`${env.apiBaseUrl}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...(t ? { Authorization: `Bearer ${t}` } : {}) },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok || !resp.body) {
    let detail = resp.statusText;
    try {
      const j = await resp.json();
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(resp.status, detail);
  }
  yield* readSse(resp.body);
}

export const chatApi = {
  conversations: () => apiFetch<Conversation[]>("/api/conversations"),
  conversation: (id: string) => apiFetch<ConversationDetail>(`/api/conversations/${id}`),
  remove: (id: string) => apiFetch<{ ok: boolean }>(`/api/conversations/${id}`, { method: "DELETE" }),
  modes: () => apiFetch<ChatMode[]>("/api/chat/modes"),
  rename: (id: string, title: string) =>
    apiFetch<{ id: string; title: string }>(`/api/conversations/${id}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  /** Drops the n-th user message and everything after it; returns that message's text. */
  rewind: (id: string, userIndex: number) =>
    apiFetch<{ ok: boolean; text: string; removed: number }>(`/api/conversations/${id}/rewind`, {
      method: "POST", body: JSON.stringify({ user_index: userIndex }),
    }),
  send: (message: string, conversationId: string | null, mode: string | null = null, signal?: AbortSignal) =>
    streamPost("/api/chat", { message, conversation_id: conversationId, mode }, signal),
  decide: (approvalId: string, approve: boolean, signal?: AbortSignal) =>
    streamPost(`/api/approvals/${approvalId}/decision`, { approve }, signal),
};
