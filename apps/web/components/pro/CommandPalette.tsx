"use client";

import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { CornerDownLeft, Search } from "lucide-react";
import { Kbd } from "@/components/pro/ui";
import type { LucideIcon } from "lucide-react";

export type Command = {
  id: string;
  group: string;
  label: string;
  hint?: string;
  icon?: LucideIcon;
  logo?: ReactNode;
  shortcut?: string[];
  keywords?: string;
};

/** Cmd/Ctrl+K palette: navigate, start a chat, switch mode, run a workflow. A floating glass layer. */
export function CommandPalette({ open, onClose, commands, onRun }: {
  open: boolean; onClose: () => void; commands: Command[]; onRun: (c: Command) => void;
}) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter((c) => `${c.label} ${c.group} ${c.hint ?? ""} ${c.keywords ?? ""}`.toLowerCase().includes(q));
  }, [commands, query]);

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    const prev = document.activeElement as HTMLElement | null;
    return () => prev?.focus?.();
  }, [open]);

  if (!open) return null;

  const active = Math.min(index, Math.max(results.length - 1, 0));
  const groups = results.reduce<Record<string, Command[]>>((acc, c) => { (acc[c.group] ??= []).push(c); return acc; }, {});

  function run(c: Command | undefined) {
    if (!c) return;
    onRun(c);
    setQuery("");
    setIndex(0);
    onClose();
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") { e.preventDefault(); onClose(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setIndex((i) => (results.length ? (i + 1) % results.length : 0)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIndex((i) => (results.length ? (i + results.length - 1) % results.length : 0)); }
    else if (e.key === "Enter") { e.preventDefault(); run(results[active]); }
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-start justify-center px-4 pt-[14vh]" onKeyDown={onKeyDown}>
      <div aria-hidden className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div role="dialog" aria-modal="true" aria-label="Command palette" className="p-float p-in relative w-full max-w-lg overflow-hidden rounded-xl">
        <div className="flex items-center gap-2.5 border-b border-p-line px-3.5">
          <Search size={15} strokeWidth={1.75} aria-hidden className="text-p-muted" />
          <input ref={inputRef} role="combobox" aria-expanded="true" aria-controls={listId} aria-autocomplete="list"
            aria-activedescendant={results[active] ? `${listId}-${results[active].id}` : undefined}
            aria-label="Search commands" value={query} onChange={(e) => { setQuery(e.target.value); setIndex(0); }}
            placeholder="Type a command or search…"
            className="h-11 min-w-0 flex-1 bg-transparent text-sm text-p-text placeholder:text-p-muted focus:outline-none" />
          <Kbd>Esc</Kbd>
        </div>
        <ul id={listId} role="listbox" aria-label="Commands" className="max-h-80 overflow-y-auto p-1.5">
          {results.length === 0 && <li className="px-3 py-6 text-center text-[13px] text-p-muted">No commands match “{query}”.</li>}
          {Object.entries(groups).map(([group, items]) => (
            <li key={group} role="presentation">
              <p className="px-2.5 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-p-muted">{group}</p>
              <ul role="presentation">
                {items.map((c) => {
                  const i = results.indexOf(c);
                  const Icon = c.icon;
                  return (
                    <li key={c.id} id={`${listId}-${c.id}`} role="option" aria-selected={i === active}
                      onMouseMove={() => setIndex(i)} onMouseDown={(e) => { e.preventDefault(); run(c); }}
                      className={`flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] ${i === active ? "bg-p-surface-3 text-p-text" : "text-p-text"}`}>
                      {c.logo ?? (Icon && <Icon size={15} strokeWidth={1.75} aria-hidden className="text-p-muted" />)}
                      <span className="flex-1 truncate">{c.label}</span>
                      {c.hint && <span className="truncate text-xs text-p-muted">{c.hint}</span>}
                      {c.shortcut && <span className="flex gap-1">{c.shortcut.map((k) => <Kbd key={k}>{k}</Kbd>)}</span>}
                      {i === active && !c.shortcut && <CornerDownLeft size={12} aria-hidden className="text-p-muted" />}
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ul>
        <div className="flex items-center gap-3 border-t border-p-line px-3.5 py-2 text-[11px] text-p-muted">
          <span><Kbd>↑</Kbd> <Kbd>↓</Kbd> navigate</span><span><Kbd>↵</Kbd> select</span>
        </div>
      </div>
    </div>
  );
}

/** Opens on Cmd/Ctrl+K and closes on a second press. */
export function usePaletteShortcut(toggle: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); toggle(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle]);
}
