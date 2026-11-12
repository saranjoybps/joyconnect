"use client";

import { useMemo, useState } from "react";
import type { NodeType } from "@/lib/workflows";

export const DRAG_MIME = "application/x-workflow-node";

const ORDER = ["trigger", "flow", "data", "ai", "human", "app"];
const TITLES: Record<string, string> = {
  trigger: "Triggers", flow: "Flow", data: "Data", ai: "AI", human: "Human", app: "App actions",
};

/** Drag-and-drop palette generated from the node registry (GET /api/node-types). Click or press Enter to add too. */
export function NodePalette({ types, onAdd }: { types: NodeType[]; onAdd: (nt: NodeType) => void }) {
  const [q, setQ] = useState("");
  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const hit = types.filter((t) => !needle || `${t.name} ${t.type} ${t.description}`.toLowerCase().includes(needle));
    const map = new Map<string, NodeType[]>();
    for (const t of hit) map.set(t.category, [...(map.get(t.category) ?? []), t]);
    return [...map.entries()].sort((a, b) => (ORDER.indexOf(a[0]) + 99) % 99 - (ORDER.indexOf(b[0]) + 99) % 99);
  }, [types, q]);

  return (
    <aside aria-label="Node palette" className="flex h-full w-60 shrink-0 flex-col border-r border-m-line bg-m-window">
      <div className="p-2">
        <label htmlFor="palette-search" className="sr-only">Search nodes</label>
        <input
          id="palette-search"
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search nodes…"
          className="w-full rounded-lg border border-line-strong bg-field px-2 py-1.5 text-sm"
        />
        <p className="mt-1 text-xs text-m-muted">Drag onto the canvas, or click to add.</p>
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {groups.length === 0 && <p className="p-2 text-sm text-m-muted">No node matches “{q}”.</p>}
        {groups.map(([cat, items]) => (
          <details key={cat} open={cat !== "app" || q !== ""} className="mb-2">
            <summary className="cursor-pointer py-1 text-xs font-semibold uppercase tracking-wide text-m-muted">
              {TITLES[cat] ?? cat} <span className="font-normal">({items.length})</span>
            </summary>
            <ul className="space-y-1">
              {items.map((t) => (
                <li key={t.type}>
                  <button
                    type="button"
                    draggable
                    title={t.description}
                    onDragStart={(e) => {
                      e.dataTransfer.setData(DRAG_MIME, t.type);
                      e.dataTransfer.effectAllowed = "move";
                    }}
                    onClick={() => onAdd(t)}
                    className="flex w-full items-center justify-between gap-2 rounded-xl border border-m-line bg-m-panel px-2.5 py-1.5 text-left text-[13px] hover:bg-m-soft"
                  >
                    <span className="truncate">{t.name}</span>
                    {t.risk !== "read" && !t.dynamic_risk && (
                      <span className={`text-[10px] font-medium uppercase ${t.risk === "destructive" ? "text-m-bad" : "text-m-warn"}`}>
                        {t.risk}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          </details>
        ))}
      </div>
    </aside>
  );
}
