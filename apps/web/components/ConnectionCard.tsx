"use client";

import { useState } from "react";
import type { Connection, Connector } from "@/lib/connections";

type Props = {
  connector: Connector;
  connections: Connection[];
  busy: boolean;
  onConnect: (connector: Connector) => void;
  onDisconnect: (connection: Connection) => void;
  onToggleAutoApprove: (connection: Connection, value: boolean) => void;
};

function StatusBadge({ connector, connections }: { connector: Connector; connections: Connection[] }) {
  let text = "Not connected";
  let cls = "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300";
  if (!connector.configured) {
    text = "Unavailable";
  } else if (connections.some((c) => c.status === "needs_reauth")) {
    text = "Needs reconnect";
    cls = "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200";
  } else if (connections.length > 0) {
    text = "Connected";
    cls = "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200";
  }
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{text}</span>;
}

export function ConnectionCard({ connector, connections, busy, onConnect, onDisconnect, onToggleAutoApprove }: Props) {
  const [confirming, setConfirming] = useState<string | null>(null);
  const needsReauth = connections.some((c) => c.status === "needs_reauth");
  const headingId = `conn-${connector.id}`;

  return (
    <article aria-labelledby={headingId}
      className="flex flex-col gap-3 rounded-xl border border-neutral-200 p-4 dark:border-neutral-800">
      <div className="flex items-start gap-3">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={connector.icon} alt="" width={40} height={40} className="h-10 w-10 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 id={headingId} className="font-medium">{connector.name}</h2>
            <StatusBadge connector={connector} connections={connections} />
          </div>
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">{connector.description}</p>
        </div>
      </div>

      {connections.length > 0 && (
        <ul className="space-y-2">
          {connections.map((c) => (
            <li key={c.id} className="rounded-lg bg-neutral-50 p-3 text-sm dark:bg-neutral-900">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="truncate font-medium">{c.account_label ?? "Account"}</span>
                {confirming === c.id ? (
                  <span className="flex gap-2">
                    <button type="button" disabled={busy}
                      onClick={() => { setConfirming(null); onDisconnect(c); }}
                      className="rounded-md bg-red-600 px-2 py-1 text-xs font-medium text-white disabled:opacity-50">
                      Confirm disconnect
                    </button>
                    <button type="button" onClick={() => setConfirming(null)} className="text-xs underline">Cancel</button>
                  </span>
                ) : (
                  <button type="button" disabled={busy} onClick={() => setConfirming(c.id)}
                    className="text-xs text-red-700 underline disabled:opacity-50 dark:text-red-400">
                    Disconnect
                  </button>
                )}
              </div>
              <label className="mt-2 flex items-center gap-2">
                <input type="checkbox" checked={c.auto_approve_writes} disabled={busy}
                  onChange={(e) => onToggleAutoApprove(c, e.target.checked)} />
                <span>Auto-approve writes</span>
              </label>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-auto flex flex-wrap items-center gap-3">
        {connector.configured && connector.auth_type === "oauth2" && (
          <button type="button" disabled={busy} onClick={() => onConnect(connector)}
            className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-neutral-900">
            {needsReauth ? "Reconnect" : connections.length > 0 ? "Connect another account" : "Connect"}
          </button>
        )}
        {!connector.configured && (
          <span className="text-sm text-neutral-500">Not set up on this server yet.</span>
        )}
        {connector.setup_url && connections.length > 0 && (
          <a href={connector.setup_url} target="_blank" rel="noreferrer" className="text-sm underline">
            Choose repositories
          </a>
        )}
      </div>
    </article>
  );
}
