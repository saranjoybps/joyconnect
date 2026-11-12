"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import type { Workflow } from "@/lib/workflow-schema";
import { workflowsApi, type Operation } from "@/lib/workflows";

export type Notice = { kind: "error" | "info"; message: string; details?: string[] };

/**
 * Holds the workflow document and sends every edit through the patch API.
 * Edits are sent one at a time with the latest `version` as `base_version`; if the server reports a conflict
 * (409) the latest document it returns replaces ours and the user is told.
 */
export function useWorkflow(id: string) {
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [publishedVersion, setPublishedVersion] = useState<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [saving, setSaving] = useState(0);
  const doc = useRef<Workflow | null>(null);
  const chain = useRef<Promise<unknown>>(Promise.resolve());

  const adopt = useCallback((w: Workflow, published?: number | null) => {
    doc.current = w;
    setWorkflow(w);
    if (published !== undefined) setPublishedVersion(published);
  }, []);

  const reload = useCallback(async () => {
    try {
      const r = await workflowsApi.get(id);
      adopt(r.workflow, r.published_version);
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof ApiError ? (e.status === 404 ? "This workflow does not exist." : e.message) : "Could not load the workflow.");
    }
  }, [id, adopt]);

  useEffect(() => {
    void reload();
  }, [reload]);

  /** Apply operations atomically. Resolves true when the server accepted them. */
  const apply = useCallback(
    (operations: Operation[]): Promise<boolean> => {
      const run = async (): Promise<boolean> => {
        const current = doc.current;
        if (!current) return false;
        setSaving((n) => n + 1);
        try {
          const r = await workflowsApi.patch(id, current.version, operations);
          adopt(r.workflow);
          setNotice(null);
          return true;
        } catch (e) {
          if (e instanceof ApiError && e.status === 409 && e.detail.current) {
            adopt(e.detail.current as Workflow);
            setNotice({ kind: "info", message: "This workflow was changed somewhere else, so it was reloaded. Please repeat your last change." });
          } else if (e instanceof ApiError) {
            const errors = Array.isArray(e.detail.errors) ? (e.detail.errors as unknown as string[]) : undefined;
            setNotice({ kind: "error", message: e.message, details: errors && errors.length > 1 ? errors : undefined });
          } else {
            setNotice({ kind: "error", message: "Could not save the change." });
          }
          return false;
        } finally {
          setSaving((n) => n - 1);
        }
      };
      const p = chain.current.then(run, run);
      chain.current = p;
      return p;
    },
    [id, adopt],
  );

  return { workflow, publishedVersion, loadError, notice, setNotice, saving: saving > 0, apply, adopt, reload };
}
