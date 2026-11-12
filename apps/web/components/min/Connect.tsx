"use client";

import { useId, useMemo, useState, type ReactNode } from "react";
import { Search } from "lucide-react";
import { LogoTile, MButton, Status, type Tone } from "@/components/min/ui";

export type ConnectorItem = {
  id: string; name: string; description: string; logo: ReactNode; status: "connected" | "partial" | "ready" | "not_set_up"; account?: string;
};

const STATUS: Record<ConnectorItem["status"], { text: string; tone: Tone; action: string; order: number }> = {
  connected: { text: "Connected", tone: "ok", action: "Manage", order: 0 },
  partial: { text: "Partial access", tone: "warn", action: "Reconnect", order: 1 },
  ready: { text: "Ready to connect", tone: "neutral", action: "Connect", order: 2 },
  not_set_up: { text: "Not set up", tone: "neutral", action: "Set up", order: 3 },
};

/** Clean grid, sorted Connected first. Setup happens in a modal (not shown here). */
export function ConnectorGrid({ items }: { items: ConnectorItem[] }) {
  const [q, setQ] = useState("");
  const searchId = useId();
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    return items
      .filter((c) => !s || `${c.name} ${c.description}`.toLowerCase().includes(s))
      .sort((a, b) => STATUS[a.status].order - STATUS[b.status].order || a.name.localeCompare(b.name));
  }, [items, q]);
  return (
    <div className="mx-auto h-full max-w-4xl overflow-y-auto px-6 pb-8">
      <div className="flex flex-wrap items-end justify-between gap-3 pb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Connections</h1>
          <p className="mt-1 text-[13px] text-m-muted">Connect your apps once, then use them from chat and workflows.</p>
        </div>
        <div className="relative w-56">
          <Search size={14} strokeWidth={1.75} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-m-muted" />
          <label htmlFor={searchId} className="sr-only">Search apps</label>
          <input id={searchId} type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search apps"
            className="h-9 w-full rounded-full border border-m-line-strong bg-m-panel pl-8 pr-3 text-[13px] placeholder:text-m-muted focus-visible:border-m-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-m-accent/25" />
        </div>
      </div>
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {shown.map((c) => {
          const s = STATUS[c.status];
          return (
            <li key={c.id} className="flex flex-col gap-3 rounded-2xl border border-m-line bg-m-panel p-4 shadow-[var(--m-shadow)] transition-colors duration-150 hover:border-m-line-strong">
              <div className="flex items-start justify-between">
                <LogoTile size={36}>{c.logo}</LogoTile>
                <Status tone={s.tone}>{s.text}</Status>
              </div>
              <div className="min-w-0 flex-1">
                <h2 className="text-sm font-medium">{c.name}</h2>
                <p className="mt-0.5 line-clamp-2 text-xs leading-5 text-m-muted">{c.description}</p>
                {c.account && <p className="mt-1.5 truncate font-mono text-[11px] text-m-muted">{c.account}</p>}
              </div>
              <MButton variant={c.status === "connected" ? "secondary" : "primary"} size="md" aria-label={`${s.action} ${c.name}`} className="w-full">{s.action}</MButton>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
