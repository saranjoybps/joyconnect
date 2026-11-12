"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Badge, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input, Select } from "@/components/ui/Field";
import { BrainIcon } from "@/components/ui/icons";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { ApiError } from "@/lib/api";
import { memoryApi, type Memory, type MemoryKind } from "@/lib/memory";

const KIND_LABEL: Record<MemoryKind, string> = {
  fact: "Fact",
  preference: "Preference",
  task: "Recurring task",
  identifier: "Key ID",
};

export function MemoryView() {
  const { toast } = useToast();
  const [items, setItems] = useState<Memory[] | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const [kind, setKind] = useState<MemoryKind>("fact");
  const [editing, setEditing] = useState<{ id: string; content: string } | null>(null);
  const [confirmAll, setConfirmAll] = useState(false);

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

  async function run(action: () => Promise<unknown>, fallback: string, done?: string) {
    setBusy(true);
    try {
      await action();
      await load();
      if (done) toast(done, "success");
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
    }, "Could not save the memory.", "Memory saved");
  }

  async function save() {
    if (!editing) return;
    await run(async () => {
      await memoryApi.update(editing.id, { content: editing.content.trim() });
      setEditing(null);
    }, "Could not update the memory.");
  }

  return (
    <section aria-labelledby="mem-title" className="space-y-6">
      <PageHeader id="mem-title" title="Memory"
        description="Short facts the assistant remembers between chats, such as your name, preferences and the sheets you use. Passwords, tokens and the content of your files are never stored. You can edit or delete anything here."
        actions={
          <label className="flex cursor-pointer items-center gap-3 text-sm font-medium">
            Memory is {enabled ? "on" : "off"}
            <input type="checkbox" role="switch" checked={enabled} disabled={busy} onChange={toggle}
              className="relative h-6 w-11 shrink-0 cursor-pointer appearance-none rounded-full bg-line-strong transition-colors checked:bg-accent disabled:opacity-50 after:absolute after:left-0.5 after:top-0.5 after:size-5 after:rounded-full after:bg-background after:transition-transform checked:after:translate-x-5" />
          </label>
        } />

      {!enabled && (
        <p className="rounded-xl border border-warn/40 p-3 text-sm text-warn">
          Memory is off: nothing new is saved and nothing is used in your chats. Your saved memories are kept until you
          delete them.
        </p>
      )}
      {error && <p role="alert" className="rounded-xl border border-bad/40 p-3 text-sm text-bad">{error}</p>}

      <form onSubmit={add} className="flex flex-wrap gap-2">
        <label className="sr-only" htmlFor="mem-new">New memory</label>
        <Input id="mem-new" value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={300}
          placeholder="Add something to remember, e.g. “My main sheet is Test Leads.”" className="min-w-64 flex-1" />
        <label className="sr-only" htmlFor="mem-kind">Kind</label>
        <Select id="mem-kind" value={kind} onChange={(e) => setKind(e.target.value as MemoryKind)} className="w-auto">
          {(Object.keys(KIND_LABEL) as MemoryKind[]).map((k) => (
            <option key={k} value={k}>{KIND_LABEL[k]}</option>
          ))}
        </Select>
        <Button type="submit" disabled={busy || !draft.trim()}>Add memory</Button>
      </form>

      {items === null && !error && (
        <div className="space-y-2" aria-label="Loading memories">
          <Skeleton className="h-14" /><Skeleton className="h-14" /><Skeleton className="h-14" />
        </div>
      )}
      {items?.length === 0 && (
        <EmptyState icon={<BrainIcon width={28} height={28} />} title="Nothing remembered yet">
          Facts from your chats will show up here.
        </EmptyState>
      )}

      <ul className="space-y-2">
        {items?.map((m) => (
          <li key={m.id} className="flex flex-wrap items-center gap-3 glass rounded-2xl p-3.5">
            <Badge>{KIND_LABEL[m.kind] ?? m.kind}</Badge>
            {editing?.id === m.id ? (
              <>
                <Input aria-label="Edit memory" value={editing.content} maxLength={300}
                  onChange={(e) => setEditing({ id: m.id, content: e.target.value })} className="min-w-64 flex-1" />
                <Button size="sm" onClick={save} disabled={busy}>Save</Button>
                <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
              </>
            ) : (
              <>
                <span className="min-w-48 flex-1 text-sm">{m.content}</span>
                <Button size="sm" variant="ghost" onClick={() => setEditing({ id: m.id, content: m.content })}>Edit</Button>
                <Button size="sm" variant="ghost" className="text-bad" aria-label={`Delete memory: ${m.content}`}
                  onClick={() => run(() => memoryApi.remove(m.id), "Could not delete the memory.", "Memory deleted")}>
                  Delete
                </Button>
              </>
            )}
          </li>
        ))}
      </ul>

      {!!items?.length && (
        <Button variant="danger" size="sm" disabled={busy} onClick={() => setConfirmAll(true)}>Delete all memories</Button>
      )}

      <Modal alert open={confirmAll} onClose={() => setConfirmAll(false)} title="Delete all memories?"
        description="The assistant will forget everything saved here. This cannot be undone."
        footer={<>
          <Button variant="secondary" onClick={() => setConfirmAll(false)}>Cancel</Button>
          <Button variant="danger" onClick={() => { setConfirmAll(false); void run(() => memoryApi.removeAll(), "Could not delete the memories.", "All memories deleted"); }}>
            Yes, delete everything
          </Button>
        </>}>
        <p className="text-sm text-muted">{items?.length ?? 0} saved memories will be removed.</p>
      </Modal>
    </section>
  );
}
