import Link from "next/link";
import type { Action } from "@/lib/chat";

type Props = {
  label: string;
  status: "running" | "ok" | "error";
  summary?: string | null;
  action?: Action | null;
  onRetry?: () => void;
  retryDisabled?: boolean;
};

/** One tool call in the actions list; on failure a clear error block with Reconnect or Retry. */
export function ActionCard({ label, status, summary, action, onRetry, retryDisabled }: Props) {
  if (status === "error") {
    const message = action?.result || summary || "This action failed.";
    const needsReconnect = action?.error_kind === "auth" || action?.error_kind === "scope";
    return (
      <div role="alert" className="max-w-[85%] rounded-lg border border-red-300 bg-red-50 p-3 text-sm dark:border-red-900 dark:bg-red-950/40">
        <p className="font-medium text-red-800 dark:text-red-300">✕ {label} failed</p>
        <p className="mt-1 text-red-800 dark:text-red-300">{message}</p>
        <div className="mt-2 flex gap-2">
          {needsReconnect ? (
            <Link href="/connections" className="rounded-md bg-red-700 px-2.5 py-1 text-xs font-medium text-white">
              Reconnect{action ? ` ${action.connector_name}` : ""}
            </Link>
          ) : onRetry ? (
            <button type="button" onClick={onRetry} disabled={retryDisabled}
              className="rounded-md bg-red-700 px-2.5 py-1 text-xs font-medium text-white disabled:opacity-50">Retry</button>
          ) : null}
        </div>
      </div>
    );
  }
  return (
    <div className="flex w-fit max-w-[85%] flex-wrap items-center gap-x-2 rounded-lg border border-neutral-200 px-3 py-1.5 text-xs dark:border-neutral-700">
      <span aria-hidden="true">{status === "running" ? "⏳" : "✓"}</span>
      <span className="font-medium">{label}{status === "running" ? "…" : ""}</span>
      {status === "ok" && action?.result && action.result !== "Done" ? (
        <span className="text-neutral-600 dark:text-neutral-400">{action.result}</span>
      ) : null}
      {status === "ok" && action?.link ? (
        <a href={action.link} target="_blank" rel="noopener noreferrer"
          className="font-medium text-blue-700 underline dark:text-blue-400">Open ↗</a>
      ) : null}
    </div>
  );
}
