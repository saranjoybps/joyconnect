"use client";

import { useId, useMemo, useState } from "react";
import { MoreHorizontal, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { MButton, MIconButton, Popover } from "@/components/min/ui";

export type ChatSummary = { id: string; title: string; preview: string; time: string };

export function HistoryPanel({ chats, activeId, onOpen, onNew }: {
  chats: ChatSummary[]; activeId?: string | null; onOpen: (id: string) => void; onNew: () => void;
}) {
  const [query, setQuery] = useState("");
  const searchId = useId();
  const [menu, setMenu] = useState<string | null>(null);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? chats.filter((c) => `${c.title} ${c.preview}`.toLowerCase().includes(q)) : chats;
  }, [chats, query]);

  return (
    <section aria-label="Chat history" className="flex h-full w-72 flex-col rounded-2xl border border-m-line bg-m-panel shadow-[var(--m-shadow)]">
      <div className="px-4 pb-3 pt-4">
        <h2 className="text-[15px] font-semibold tracking-tight">Chat history</h2>
        <div className="relative mt-3">
          <Search size={14} strokeWidth={1.75} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-m-muted" />
          <label htmlFor={searchId} className="sr-only">Search chats</label>
          <input id={searchId} type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search…"
            className="h-9 w-full rounded-full border border-m-line-strong bg-m-window pl-8 pr-3 text-[13px] placeholder:text-m-muted focus-visible:border-m-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-m-accent/25" />
        </div>
      </div>

      <ul className="min-h-0 flex-1 divide-y divide-m-line overflow-y-auto px-2">
        {shown.length === 0 && <li className="px-2 py-6 text-center text-[13px] text-m-muted">No chats match your search.</li>}
        {shown.map((c) => (
          <li key={c.id} className="group relative">
            <button type="button" onClick={() => onOpen(c.id)} aria-current={c.id === activeId ? "true" : undefined}
              className={`block w-full rounded-xl px-2.5 py-3 pr-9 text-left transition-colors duration-150 hover:bg-m-soft ${c.id === activeId ? "bg-m-soft" : ""}`}>
              <span className="block truncate text-[13px] font-medium">{c.title}</span>
              <span className="mt-0.5 block truncate text-xs text-m-muted">{c.preview}</span>
              <span className="mt-1.5 block text-right text-[11px] text-m-muted">{c.time}</span>
            </button>
            <div className="absolute right-1 top-2">
              <MIconButton label={`Options for ${c.title}`} icon={MoreHorizontal} size={26} aria-haspopup="menu" aria-expanded={menu === c.id}
                className="opacity-0 focus-visible:opacity-100 group-hover:opacity-100 aria-expanded:opacity-100" onClick={() => setMenu(menu === c.id ? null : c.id)} />
              <Popover open={menu === c.id} onClose={() => setMenu(null)} label={`${c.title} menu`} className="right-0 top-8 w-36">
                <button type="button" onClick={() => setMenu(null)} className="flex h-8 w-full items-center gap-2 rounded-lg px-2.5 text-[13px] hover:bg-m-soft"><Pencil size={13} aria-hidden />Rename</button>
                <button type="button" onClick={() => setMenu(null)} className="flex h-8 w-full items-center gap-2 rounded-lg px-2.5 text-[13px] text-m-bad hover:bg-m-bad/10"><Trash2 size={13} aria-hidden />Delete</button>
              </Popover>
            </div>
          </li>
        ))}
      </ul>

      <div className="p-3">
        <MButton size="lg" icon={Plus} className="w-full" onClick={onNew}>Create new chat</MButton>
      </div>
    </section>
  );
}
