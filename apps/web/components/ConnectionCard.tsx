"use client";

import { useState } from "react";
import { ProviderSetupPanel } from "@/components/ProviderSetupPanel";
import { cardState, scopeLabel, type CardState, type Connection, type Connector } from "@/lib/connections";

type Props = {
  connector: Connector;
  connections: Connection[];
  busy: boolean;
  onConnect: (connector: Connector) => void;
  onDisconnect: (connection: Connection) => void;
  onToggleAutoApprove: (connection: Connection, value: boolean) => void;
  onSetupChanged: () => void;
};

const BADGE: Record<CardState, { text: string; cls: string }> = {
  not_set_up: { text: "Not set up", cls: "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300" },
  ready: { text: "Ready to connect", cls: "bg-sky-100 text-sky-900 dark:bg-sky-900/40 dark:text-sky-200" },
  partial: { text: "Partial access", cls: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200" },
  connected: { text: "Connected", cls: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200" },
  needs_reconnect: { text: "Needs reconnect", cls: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200" },
};

export function ConnectionCard({
  connector, connections, busy, onConnect, onDisconnect, onToggleAutoApprove, onSetupChanged,
}: Props) {
  const [confirming, setConfirming] = useState<string | null>(null);
  const state = cardState(connector, connections);
  const [setupOpen, setSetupOpen] = useState(false);
  const headingId = `conn-${connector.id}`;
  const badge = BADGE[state];
  const { setup } = connector;

  const connectLabel = state === "needs_reconnect" || state === "partial" ? "Reconnect"
    : state === "connected" ? "Connect another account" : "Connect";

  return (
    <article aria-labelledby={headingId}
      className="flex flex-col gap-3 rounded-xl border border-neutral-200 p-4 dark:border-neutral-800">
      <div className="flex items-start gap-3">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={connector.icon} alt="" width={40} height={40} className="h-10 w-10 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 id={headingId} className="font-medium">{connector.name}</h2>
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${badge.cls}`}>{badge.text}</span>
          </div>
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">{connector.description}</p>
          {setup.source === "user" && setup.client_id_masked && (
            <p className="mt-1 text-xs text-neutral-500">Your app: <code>{setup.client_id_masked}</code></p>
          )}
          {setup.source === "platform" && (
            <p className="mt-1 text-xs text-neutral-500">Using this server&apos;s default app</p>
          )}
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
              {c.partial && (
                <p role="alert" className="mt-2 rounded-md bg-amber-50 p-2 text-xs text-amber-950 dark:bg-amber-950/40 dark:text-amber-100">
                  {connector.auth_type === "oauth2" ? "The provider" : "This app"} did not grant:{" "}
                  {(c.missing_scopes ?? []).map(scopeLabel).join(", ")}. Reconnect {connector.name} and tick the{" "}
                  {connector.name.replace(/^Google /, "")} permission on the consent screen.
                </p>
              )}
              {c.scopes.length > 0 && (
                <details className="mt-2 text-xs text-neutral-600 dark:text-neutral-400">
                  <summary className="cursor-pointer">Granted permissions ({c.scopes.length})</summary>
                  <ul className="mt-1 list-disc pl-4">
                    {c.scopes.map((s) => <li key={s}>{scopeLabel(s)}</li>)}
                  </ul>
                </details>
              )}
              <label className="mt-2 flex items-center gap-2">
                <input type="checkbox" checked={c.auto_approve_writes} disabled={busy}
                  onChange={(e) => onToggleAutoApprove(c, e.target.checked)} />
                <span>Auto-approve writes</span>
              </label>
            </li>
          ))}
        </ul>
      )}

      {setupOpen && (
        <ProviderSetupPanel
          connector={connector}
          onSaved={onSetupChanged}
          onRemoved={() => { setSetupOpen(false); onSetupChanged(); }}
          onClose={() => setSetupOpen(false)}
        />
      )}

      <div className="mt-auto flex flex-wrap items-center gap-3">
        {state === "not_set_up" ? (
          !setupOpen && (
            <button type="button" onClick={() => setSetupOpen(true)}
              className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white dark:bg-white dark:text-neutral-900">
              Set up
            </button>
          )
        ) : (
          <>
            <button type="button" disabled={busy} onClick={() => onConnect(connector)}
              className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-neutral-900">
              {connectLabel}
            </button>
            {!setupOpen && (
              <button type="button" onClick={() => setSetupOpen(true)} className="text-sm underline">
                {setup.source === "user" ? "Edit setup" : "Use my own app"}
              </button>
            )}
          </>
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
