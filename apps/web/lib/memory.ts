import { apiFetch } from "@/lib/api";

export type MemoryKind = "fact" | "preference" | "task" | "identifier";

export type Memory = {
  id: string;
  kind: MemoryKind;
  content: string;
  created_at: string | null;
  updated_at: string | null;
};

export type MemoryList = { enabled: boolean; kinds: MemoryKind[]; memories: Memory[] };

const enc = encodeURIComponent;

export const memoryApi = {
  list: () => apiFetch<MemoryList>("/api/memories"),
  add: (content: string, kind: MemoryKind) =>
    apiFetch<Memory>("/api/memories", { method: "POST", body: JSON.stringify({ content, kind }) }),
  update: (id: string, patch: { content?: string; kind?: MemoryKind }) =>
    apiFetch<Memory>(`/api/memories/${enc(id)}`, { method: "PATCH", body: JSON.stringify(patch) }),
  remove: (id: string) => apiFetch<void>(`/api/memories/${enc(id)}`, { method: "DELETE" }),
  removeAll: () => apiFetch<{ deleted: number }>("/api/memories", { method: "DELETE" }),
  setEnabled: (memory_enabled: boolean) =>
    apiFetch<{ memory_enabled: boolean }>("/api/memory/settings", { method: "PUT", body: JSON.stringify({ memory_enabled }) }),
};
