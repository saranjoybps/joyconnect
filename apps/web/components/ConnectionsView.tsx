"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ConnectionCard } from "@/components/ConnectionCard";
import { ConnectModal } from "@/components/connections/ConnectModal";
import { EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input } from "@/components/ui/Field";
import { Tabs } from "@/components/ui/Tabs";
import { SearchIcon } from "@/components/ui/icons";
import { useToast } from "@/components/ui/Toast";
import {
  CATEGORIES, categoryOf, cardState, connectionsApi, describeOAuthError, type Connection, type Connector,
} from "@/lib/connections";

// Connected first, then apps needing attention, then ready, then not set up (each group A to Z).
const ORDER = { connected: 0, partial: 1, needs_reconnect: 1, ready: 2, not_set_up: 3 } as const;

export function ConnectionsView() {
  const params = useSearchParams();
  const router = useRouter();
  const { toast } = useToast();
  const [connectors, setConnectors] = useState<Connector[] | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>("All");
  const [openId, setOpenId] = useState<string | null>(null);

  const notice = useMemo(() => {
    const connected = params.get("connected");
    const err = params.get("error");
    const partial = params.get("partial");
    if (err) return { kind: "error" as const, text: describeOAuthError(err) };
    if (partial) {
      return { kind: "warn" as const,
        text: `Connected, but Google did not grant the ${partial} permission. Click Reconnect and tick the ${partial} permission on Google's consent screen.` };
    }
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

  async function run(action: () => Promise<unknown>, done?: (r: unknown) => void) {
    setBusy(true);
    setError(null);
    try {
      const r = await action();
      done?.(r);
      setReloadKey((k) => k + 1);
    } catch (e) {
      setError((e as Error).message);
      toast((e as Error).message, "error");
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
      toast((e as Error).message, "error");
      setReloadKey((k) => k + 1);
      setBusy(false);
    }
  }

  const categories = useMemo(() => {
    const present = new Set((connectors ?? []).map((c) => categoryOf(c.id)));
    return ["All", ...CATEGORIES.filter((c) => present.has(c))];
  }, [connectors]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rank = (c: Connector) => ORDER[cardState(c, connections.filter((x) => x.provider === c.id))];
    return (connectors ?? [])
      .filter((c) =>
        (category === "All" || categoryOf(c.id) === category) &&
        (!q || c.name.toLowerCase().includes(q) || c.description.toLowerCase().includes(q)))
      .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
  }, [connectors, connections, query, category]);

  const open = connectors?.find((c) => c.id === openId) ?? null;

  return (
    <section aria-labelledby="connections-title" className="space-y-6">
      <PageHeader id="connections-title" title="Connections"
        description="Set up each app with your own developer credentials, then connect. Secrets and tokens stay on the server and are never sent back to your browser." />

      {notice && (
        <div role="status"
          className={`flex items-center justify-between gap-3 rounded-xl border bg-m-panel p-3.5 text-[13px] ${notice.kind === "error" ? "border-m-bad/40 text-m-bad" : notice.kind === "warn" ? "border-m-warn/40 text-m-warn" : "border-m-ok/40 text-m-ok"}`}>
          <span>{notice.text}</span>
          <button type="button" className="underline underline-offset-4" onClick={() => router.replace("/connections")}>Dismiss</button>
        </div>
      )}
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-full sm:w-72">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <label htmlFor="connector-search" className="sr-only">Search apps</label>
          <Input id="connector-search" type="search" value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="Search apps" className="rounded-full pl-9" />
        </div>
        <Tabs label="Filter by category" controls="connector-grid" value={category} onChange={setCategory}
          tabs={categories.map((c) => ({ id: c, label: c }))} />
      </div>

      {connectors === null && !error && (
        <div aria-label="Loading apps" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-16 rounded-xl" />)}
        </div>
      )}

      {connectors !== null && visible.length === 0 && (
        <EmptyState title="No apps match" action={
          <button type="button" className="text-sm underline underline-offset-4" onClick={() => { setQuery(""); setCategory("All"); }}>Clear filters</button>
        }>
          Try a different search or category.
        </EmptyState>
      )}

      <ul id="connector-grid" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {visible.map((c) => (
          <li key={c.id}>
            <ConnectionCard connector={c} connections={connections.filter((x) => x.provider === c.id)} onOpen={(x) => setOpenId(x.id)} />
          </li>
        ))}
      </ul>

      {open && (
        <ConnectModal
          key={open.id}
          connector={open}
          connections={connections.filter((x) => x.provider === open.id)}
          busy={busy}
          onClose={() => setOpenId(null)}
          onConnect={connect}
          onDisconnect={(conn) => run(() => connectionsApi.disconnect(conn.id), () => toast("Disconnected", "success"))}
          onToggleAutoApprove={(conn, v) => run(() => connectionsApi.setAutoApprove(conn.id, v))}
          onTest={(conn) => run(() => connectionsApi.test(conn.id),
            (r) => { const h = r as { ok: boolean; message: string }; toast(h.message, h.ok ? "success" : "error"); })}
          onSetupChanged={() => setReloadKey((k) => k + 1)}
        />
      )}
    </section>
  );
}
