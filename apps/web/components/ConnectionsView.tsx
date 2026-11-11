"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ConnectionCard } from "@/components/ConnectionCard";
import {
  connectionsApi, describeOAuthError, type Connection, type Connector,
} from "@/lib/connections";

export function ConnectionsView() {
  const params = useSearchParams();
  const router = useRouter();
  const [connectors, setConnectors] = useState<Connector[] | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const notice = useMemo(() => {
    const connected = params.get("connected");
    const err = params.get("error");
    if (err) return { kind: "error" as const, text: describeOAuthError(err) };
    if (connected) return { kind: "ok" as const, text: "Connected successfully." };
    return null;
  }, [params]);

  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let alive = true;
    Promise.all([connectionsApi.connectors(), connectionsApi.list()]).then(
      ([cs, conns]) => {
        if (!alive) return;
        setConnectors(cs);
        setConnections(conns);
      },
      (e: Error) => alive && setError(e.message),
    );
    return () => { alive = false; };
  }, [reloadKey]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setReloadKey((k) => k + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function connect(c: Connector) {
    setBusy(true);
    setError(null);
    try {
      const result = await connectionsApi.start(c.id);
      if (result.authorize_url) {
        window.location.assign(result.authorize_url);
        return;
      }
      setReloadKey((k) => k + 1);
      setBusy(false);
    } catch (e) {
      setError((e as Error).message);
      setReloadKey((k) => k + 1);
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="connections-title" className="space-y-4">
      <div>
        <h1 id="connections-title" className="text-xl font-semibold">Connections</h1>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Set up each app with your own developer credentials, then connect. Secrets and tokens stay on the server and are never sent back to your browser.
        </p>
      </div>

      {notice && (
        <div role="status"
          className={`flex items-center justify-between rounded-lg p-3 text-sm ${notice.kind === "error"
            ? "bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-200"
            : "bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"}`}>
          <span>{notice.text}</span>
          <button type="button" className="underline" onClick={() => router.replace("/connections")}>Dismiss</button>
        </div>
      )}
      {error && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{error}</p>}

      {connectors === null && !error && <p className="text-sm text-neutral-500">Loading…</p>}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {connectors?.map((c) => (
          <ConnectionCard
            key={c.id}
            connector={c}
            connections={connections.filter((x) => x.provider === c.id)}
            busy={busy}
            onConnect={connect}
            onDisconnect={(conn) => run(() => connectionsApi.disconnect(conn.id))}
            onToggleAutoApprove={(conn, v) => run(() => connectionsApi.setAutoApprove(conn.id, v))}
            onSetupChanged={() => setReloadKey((k) => k + 1)}
          />
        ))}
      </div>
    </section>
  );
}
