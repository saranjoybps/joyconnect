"use client";

import Link from "next/link";
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
    <section aria-labelledby="wf-title" className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 id="wf-title" className="text-xl font-semibold">Workflows</h1>
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            Build automations on a canvas, or ask the chat to build them.
          </p>
        </div>
        <form onSubmit={create} className="flex gap-2">
          <label className="sr-only" htmlFor="wf-name">Workflow name</label>
          <input
            id="wf-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Workflow name"
            maxLength={200}
            className="rounded-md border border-neutral-300 bg-transparent px-3 py-1.5 text-sm dark:border-neutral-700"
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
          >
            New workflow
          </button>
        </form>
      </div>

      {error && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">
          {error}
        </p>
      )}
      {items === null && !error && <p className="text-sm text-neutral-600">Loading…</p>}
      {items?.length === 0 && (
        <p className="rounded-lg border border-dashed border-neutral-300 p-8 text-center text-sm text-neutral-600 dark:border-neutral-700">
          No workflows yet. Name one above and press “New workflow”.
        </p>
      )}

      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {items?.map((w) => (
          <li key={w.id} className="flex flex-col gap-2 rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
            <Link href={`/workflows/${w.id}`} className="font-medium hover:underline">{w.name}</Link>
            <div className="flex items-center gap-2 text-xs text-neutral-600 dark:text-neutral-400">
              <span
                className={`rounded-full px-2 py-0.5 font-medium ${w.status === "published" ? "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200" : "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300"}`}
              >
                {w.status === "published" ? "Published" : "Draft"}
              </span>
              <span>{w.node_count} node{w.node_count === 1 ? "" : "s"}</span>
              <span>v{w.version}</span>
            </div>
            <div className="mt-auto flex items-center justify-between pt-2 text-sm">
              <Link href={`/workflows/${w.id}`} className="underline">Open</Link>
              <button type="button" onClick={() => setConfirming(w)} className="text-red-700 underline dark:text-red-400">
                Delete
              </button>
            </div>
          </li>
        ))}
      </ul>

      {confirming && (
        <div role="alertdialog" aria-modal="true" aria-labelledby="del-title" className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4">
          <div className="w-full max-w-sm space-y-3 rounded-lg bg-white p-5 shadow-xl dark:bg-neutral-900">
            <h2 id="del-title" className="font-semibold">Delete “{confirming.name}”?</h2>
            <p className="text-sm text-neutral-600 dark:text-neutral-400">
              This removes the workflow, its versions and its run history. Schedules and webhooks stop. This cannot be undone.
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setConfirming(null)} className="rounded-md border border-neutral-300 px-3 py-1.5 text-sm dark:border-neutral-700">
                Cancel
              </button>
              <button type="button" disabled={busy} onClick={() => remove(confirming)} className="rounded-md bg-red-700 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
                Delete workflow
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
