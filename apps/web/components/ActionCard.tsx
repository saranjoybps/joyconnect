"use client";

import Link from "next/link";
import { useState } from "react";
import type { Action } from "@/lib/chat";
import { Button } from "@/components/ui/Button";
import { ChevronIcon, ExternalIcon } from "@/components/ui/icons";

type Props = {
  label: string;
  status: "running" | "ok" | "error";
  summary?: string | null;
  action?: Action | null;
  input?: Record<string, unknown> | null;
  output?: string | null;
  durationMs?: number | null;
  onRetry?: () => void;
  retryDisabled?: boolean;
};

export function formatDuration(ms: number | null | undefined): string | null {
  if (ms === null || ms === undefined) return null;
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function prettyOutput(output: string): string {
  try { return JSON.stringify(JSON.parse(output), null, 2); } catch { return output; }
}

const DOT: Record<Props["status"], string> = {
  running: "bg-muted animate-pulse",
  ok: "bg-ok",
  error: "bg-bad",
};

/** One tool call as a timeline card: name, status, duration; collapsible input and output. On failure, Reconnect or Retry. */
export function ActionCard({ label, status, summary, action, input, output, durationMs, onRetry, retryDisabled }: Props) {
  const [open, setOpen] = useState(false);
  const duration = formatDuration(durationMs);
  const hasDetails = Boolean((input && Object.keys(input).length) || output);
  const needsReconnect = action?.error_kind === "auth" || action?.error_kind === "scope";
  const message = status === "error" ? action?.result || summary || "This action failed." : null;
  const statusText = status === "running" ? "Running" : status === "ok" ? "Done" : "Failed";

  return (
    <li className="relative pl-6">
      <span aria-hidden className={`absolute left-0 top-[1.05rem] size-2.5 rounded-full ring-4 ring-[var(--glass-solid)] ${DOT[status]}`} />
      <div role={status === "error" ? "alert" : undefined}
        className={`glass-lite rounded-2xl text-sm ${status === "error" ? "!border-bad/50" : ""}`}>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5">
          <span className="font-medium">{label}{status === "error" ? " failed" : status === "running" ? "…" : ""}</span>
          <span className={`text-xs ${status === "error" ? "text-bad" : status === "ok" ? "text-ok" : "text-muted"}`}>{statusText}</span>
          {duration && <span className="text-xs text-muted">{duration}</span>}
          {status === "ok" && action?.result && action.result !== "Done" && (
            <span className="min-w-0 truncate text-xs text-muted">{action.result}</span>
          )}
          {status === "ok" && action?.link && (
            <a href={action.link} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs font-medium underline underline-offset-4">
              Open <ExternalIcon width={12} height={12} /><span className="sr-only"> (opens in a new tab)</span>
            </a>
          )}
          {hasDetails && (
            <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
              aria-label={`${open ? "Hide" : "Show"} details for ${label}`}
              className="ml-auto inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-muted hover:bg-surface-2 hover:text-foreground">
              Details <ChevronIcon width={12} height={12} className={`transition-transform ${open ? "rotate-90" : ""}`} />
            </button>
          )}
        </div>
        {message && <p className="px-3 pb-2.5 text-sm text-bad">{message}</p>}
        {status === "error" && (needsReconnect || onRetry) && (
          <div className="flex gap-2 px-3 pb-3">
            {needsReconnect ? (
              <Link href="/connections"
                className="inline-flex h-8 items-center rounded-lg bg-accent px-3 text-xs font-medium text-accent-fg hover:opacity-85">
                Reconnect{action ? ` ${action.connector_name}` : ""}
              </Link>
            ) : (
              <Button size="sm" variant="secondary" onClick={onRetry} disabled={retryDisabled}>Retry</Button>
            )}
          </div>
        )}
        {open && hasDetails && (
          <div className="space-y-3 border-t border-line px-3 py-3">
            {input && Object.keys(input).length > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium text-muted">Input</p>
                <pre className="max-h-48 overflow-auto rounded-lg bg-surface p-2 font-mono text-xs">{JSON.stringify(input, null, 2)}</pre>
              </div>
            )}
            {output && (
              <div>
                <p className="mb-1 text-xs font-medium text-muted">Output</p>
                <pre className="max-h-64 overflow-auto rounded-lg bg-surface p-2 font-mono text-xs">{prettyOutput(output)}</pre>
              </div>
            )}
          </div>
        )}
      </div>
    </li>
  );
}
