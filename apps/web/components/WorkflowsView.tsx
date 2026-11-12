"use client";

import Link from "next/link";
import { Button } from "@/components/ui/Button";
import { Badge, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input } from "@/components/ui/Field";
import { FlowIcon } from "@/components/ui/icons";
import { Modal } from "@/components/ui/Modal";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { workflowsApi, type WorkflowSummary } from "@/lib/workflows";

export function WorkflowsView() {
  const router = useRouter();
  const [items, setItems] = useState<WorkflowSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<WorkflowSummary | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await workflowsApi.list());
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load workflows.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const { workflow } = await workflowsApi.create(name.trim() || "Untitled workflow");
      router.push(`/workflows/${workflow.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the workflow.");
      setBusy(false);
    }
  }

  async function remove(w: WorkflowSummary) {
    setBusy(true);
    try {
      await workflowsApi.remove(w.id);
      setConfirming(null);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete the workflow.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="wf-title" className="space-y-6">
      <PageHeader id="wf-title" title="Workflows" description="Build automations on a canvas, or ask the chat to build them."
        actions={
          <form onSubmit={create} className="flex gap-2">
            <label className="sr-only" htmlFor="wf-name">Workflow name</label>
            <Input id="wf-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Workflow name" maxLength={200} className="w-56" />
            <Button type="submit" disabled={busy}>New workflow</Button>
          </form>
        } />

      {error && <p role="alert" className="rounded-xl border border-bad/40 p-3 text-sm text-bad">{error}</p>}
      {items === null && !error && (
        <div aria-label="Loading workflows" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Skeleton className="h-32" /><Skeleton className="h-32" /><Skeleton className="h-32" />
        </div>
      )}
      {items?.length === 0 && (
        <EmptyState icon={<FlowIcon width={28} height={28} />} title="No workflows yet">
          Name one above and press “New workflow”.
        </EmptyState>
      )}

      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {items?.map((w) => (
          <li key={w.id} className="flex flex-col gap-3 rounded-2xl border border-line p-5 transition-colors hover:border-line-strong">
            <Link href={`/workflows/${w.id}`} className="font-medium hover:underline">{w.name}</Link>
            <div className="flex items-center gap-2 text-xs text-muted">
              <Badge tone={w.status === "published" ? "success" : "neutral"}>{w.status === "published" ? "Published" : "Draft"}</Badge>
              <span>{w.node_count} node{w.node_count === 1 ? "" : "s"}</span>
              <span>v{w.version}</span>
            </div>
            <div className="mt-auto flex items-center justify-between pt-2 text-sm">
              <Link href={`/workflows/${w.id}`} className="font-medium underline underline-offset-4">Open</Link>
              <button type="button" onClick={() => setConfirming(w)} className="text-bad underline underline-offset-4">Delete</button>
            </div>
          </li>
        ))}
      </ul>

      <Modal alert open={confirming !== null} onClose={() => setConfirming(null)} title={`Delete “${confirming?.name ?? ""}”?`}
        description="This removes the workflow, its versions and its run history. Schedules and webhooks stop. This cannot be undone."
        footer={<>
          <Button variant="secondary" onClick={() => setConfirming(null)}>Cancel</Button>
          <Button variant="danger" disabled={busy} onClick={() => confirming && remove(confirming)}>Delete workflow</Button>
        </>}>
        <p className="text-sm text-muted">Chat and canvas edits to this workflow will be lost.</p>
      </Modal>
    </section>
  );
}
