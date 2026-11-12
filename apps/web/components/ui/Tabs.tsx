"use client";

import type { KeyboardEvent } from "react";

export type TabItem = { id: string; label: string };

/** Quiet segmented tabs with arrow-key navigation (roving tabindex). */
export function Tabs({ tabs, value, onChange, label, controls }: {
  tabs: TabItem[]; value: string; onChange: (id: string) => void; label: string; controls?: string;
}) {
  function onKey(e: KeyboardEvent<HTMLButtonElement>, i: number) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    onChange(next.id);
    (e.currentTarget.parentElement?.querySelector(`[data-tab="${next.id}"]`) as HTMLElement | null)?.focus();
  }
  return (
    <div role="tablist" aria-label={label} className="inline-flex flex-wrap gap-0.5 rounded-full border border-m-line bg-m-soft p-0.5">
      {tabs.map((t, i) => {
        const on = t.id === value;
        return (
          <button key={t.id} type="button" role="tab" data-tab={t.id} aria-selected={on} aria-controls={controls}
            tabIndex={on ? 0 : -1} onClick={() => onChange(t.id)} onKeyDown={(e) => onKey(e, i)}
            className={`h-7 rounded-full px-3 text-xs font-medium transition-colors ${on ? "bg-m-panel text-m-text shadow-[var(--m-shadow)]" : "text-m-muted hover:text-m-text"}`}>
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
