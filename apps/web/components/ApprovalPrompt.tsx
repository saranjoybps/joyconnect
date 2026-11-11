"use client";

import type { ApprovalPreview } from "@/lib/chat";

type Props = {
  approval: ApprovalPreview;
  state: "pending" | "submitting" | "approved" | "rejected";
  onDecide: (approve: boolean) => void;
};

function formatValue(v: unknown): string {
  if (typeof v === "string") return v;
  return JSON.stringify(v, null, 2);
}

export function ApprovalPrompt({ approval, state, onDecide }: Props) {
  const titleId = `approval-${approval.approval_id}`;
  const destructive = approval.risk === "destructive";
  return (
    <section
      aria-labelledby={titleId}
      className={`rounded-xl border p-4 ${destructive
        ? "border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950/40"
        : "border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/40"}`}
    >
      <h3 id={titleId} className="font-medium">
        Approve: {approval.connector_name} · {approval.action}
        {approval.account ? <span className="font-normal text-neutral-600 dark:text-neutral-400"> ({approval.account})</span> : null}
      </h3>
      <p className="mt-1 text-sm text-neutral-700 dark:text-neutral-300">{approval.description}</p>
      <dl className="mt-3 space-y-2 text-sm">
        {Object.entries(approval.args).map(([k, v]) => (
          <div key={k}>
            <dt className="font-medium text-neutral-600 dark:text-neutral-400">{k.replace(/_/g, " ")}</dt>
            <dd className="mt-0.5 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-white/70 px-2 py-1 font-mono text-xs dark:bg-black/30">
              {v === null ? "—" : formatValue(v)}
            </dd>
          </div>
        ))}
      </dl>
      <div className="mt-4 flex items-center gap-2">
        {state === "pending" || state === "submitting" ? (
          <>
            <button type="button" disabled={state === "submitting"} onClick={() => onDecide(true)}
              className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-neutral-900">
              Approve
            </button>
            <button type="button" disabled={state === "submitting"} onClick={() => onDecide(false)}
              className="rounded-md border border-neutral-400 px-3 py-1.5 text-sm font-medium disabled:opacity-50">
              Reject
            </button>
          </>
        ) : (
          <p role="status" className="text-sm font-medium">{state === "approved" ? "Approved" : "Rejected"}</p>
        )}
      </div>
    </section>
  );
}
