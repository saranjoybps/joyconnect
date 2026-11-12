"use client";

import type { ApprovalPreview } from "@/lib/chat";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Card";

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
    <section aria-labelledby={titleId}
      className={`anim-fade-up rounded-2xl border bg-background p-4 ${destructive ? "border-bad/50" : "border-warn/50"}`}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={titleId} className="font-medium">
          Approve: {approval.connector_name} · {approval.action}
          {approval.account ? <span className="font-normal text-muted"> ({approval.account})</span> : null}
        </h3>
        <Badge tone={destructive ? "error" : "warning"}>{destructive ? "Destructive" : "Needs approval"}</Badge>
      </div>
      <p className="mt-1 text-sm text-muted">{approval.description}</p>
      <dl className="mt-3 space-y-2 text-sm">
        {Object.entries(approval.args).map(([k, v]) => (
          <div key={k}>
            <dt className="text-xs font-medium text-muted">{k.replace(/_/g, " ")}</dt>
            <dd className="mt-0.5 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-surface px-2.5 py-1.5 font-mono text-xs">
              {v === null ? "—" : formatValue(v)}
            </dd>
          </div>
        ))}
      </dl>
      <div className="mt-4 flex items-center gap-2">
        {state === "pending" || state === "submitting" ? (
          <>
            <Button disabled={state === "submitting"} onClick={() => onDecide(true)}>Approve</Button>
            <Button variant="secondary" disabled={state === "submitting"} onClick={() => onDecide(false)}>Reject</Button>
          </>
        ) : (
          <p role="status" className="text-sm font-medium">{state === "approved" ? "Approved" : "Rejected"}</p>
        )}
      </div>
    </section>
  );
}
