"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { memoryApi, type Memory, type MemoryKind } from "@/lib/memory";

const KIND_LABEL: Record<MemoryKind, string> = {
  fact: "Fact",
  preference: "Preference",
  task: "Recurring task",
  identifier: "Key ID",
};

export function MemoryView() {
  const [items, setItems] = useState<Memory[] | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const [kind, setKind] = useState<MemoryKind>("fact");
  const [editing, setEditing] = useState<{ id: string; content: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await memoryApi.list();
      setItems(r.memories);
      setEnabled(r.enabled);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load your memories.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(action: () => Promise<unknown>, fallback: string) {
    setBusy(true);
    try {
      await action();
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : fallback);
    } finally {
      setBusy(false);
    }
  }

  async function toggle() {
    await run(() => memoryApi.setEnabled(!enabled), "Could not change the memory setting.");
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!draft.trim()) return;
    await run(async () => {
      await memoryApi.add(draft.trim(), kind);
      setDraft("");
    }, "Could not save the memory.");
  }

  async function save() {
    if (!editing) return;
    await run(async () => {
      await memoryApi.update(editing.id, { content: editing.content.trim() });
      setEditing(null);
    }, "Could not update the memory.");
  }

  return (
    <section aria-labelledby="mem-title" className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 id="mem-title" className="text-xl font-semibold">Memory</h1>
          <p className="max-w-xl text-sm text-neutral-600 dark:text-neutral-400">
            Short facts the assistant remembers between chats, such as your name, preferences and the sheets you use.
            Passwords, tokens and the content of your files are never stored. You can edit or delete anything here.
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm font-medium">
          <input type="checkbox" role="switch" checked={enabled} disabled={busy} onChange={toggle} />
          Memory is {enabled ? "on" : "off"}
        </label>
      </div>

      {!enabled && (
        <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          Memory is off: nothing new is saved and nothing is used in your chats. Your saved memories are kept until you
          delete them.
        </p>
      )}
      {error && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">
          {error}
        </p>
      )}

      <form onSubmit={add} className="flex flex-wrap gap-2">
        <label className="sr-only" htmlFor="mem-new">New memory</label>
        <input
          id="mem-new"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          maxLength={300}
          placeholder="Add something to remember, e.g. “My main sheet is Test Leads.”"
          className="min-w-64 flex-1 rounded-md border border-neutral-300 bg-transparent px-3 py-1.5 text-sm dark:border-neutral-700"
        />
        <label className="sr-only" htmlFor="mem-kind">Kind</label>
        <select
          id="mem-kind"
          value={kind}
          onChange={(e) => setKind(e.target.value as MemoryKind)}
          className="rounded-md border border-neutral-300 bg-transparent px-2 py-1.5 text-sm dark:border-neutral-700"
        >
          {(Object.keys(KIND_LABEL) as MemoryKind[]).map((k) => (
            <option key={k} value={k}>{KIND_LABEL[k]}</option>
          ))}
        </select>
        <button type="submit" disabled={busy || !draft.trim()} className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900">
          Add memory
        </button>
      </form>

      {items === null && !error && <p className="text-sm text-neutral-600">Loading…</p>}
      {items?.length === 0 && (
        <p className="rounded-lg border border-dashed border-neutral-300 p-8 text-center text-sm text-neutral-600 dark:border-neutral-700">
          Nothing remembered yet. Facts from your chats will show up here.
        </p>
      )}

      <ul className="space-y-2">
        {items?.map((m) => (
          <li key={m.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
            <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-medium dark:bg-neutral-800">{KIND_LABEL[m.kind] ?? m.kind}</span>
            {editing?.id === m.id ? (
              <>
                <input
                  aria-label="Edit memory"
                  value={editing.content}
                  onChange={(e) => setEditing({ id: m.id, content: e.target.value })}
                  maxLength={300}
                  className="min-w-64 flex-1 rounded-md border border-neutral-300 bg-transparent px-2 py-1 text-sm dark:border-neutral-700"
                />
                <button type="button" onClick={save} disabled={busy} className="text-sm underline">Save</button>
                <button type="button" onClick={() => setEditing(null)} className="text-sm underline">Cancel</button>
              </>
            ) : (
              <>
                <span className="min-w-48 flex-1 text-sm">{m.content}</span>
                <button type="button" onClick={() => setEditing({ id: m.id, content: m.content })} className="text-sm underline">Edit</button>
                <button
                  type="button"
                  aria-label={`Delete memory: ${m.content}`}
                  onClick={() => run(() => memoryApi.remove(m.id), "Could not delete the memory.")}
                  className="text-sm text-red-700 underline dark:text-red-400"
                >
                  Delete
                </button>
              </>
            )}
          </li>
        ))}
      </ul>

      {!!items?.length && (
        <button
          type="button"
          disabled={busy}
          onClick={() => run(() => memoryApi.removeAll(), "Could not delete the memories.")}
          className="text-sm text-red-700 underline dark:text-red-400"
        >
          Delete all memories
        </button>
      )}
    </section>
  );
}
