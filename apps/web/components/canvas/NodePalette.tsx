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
    <aside aria-label="Node palette" className="flex h-full w-60 shrink-0 flex-col border-r border-neutral-200 dark:border-neutral-800">
      <div className="p-2">
        <label htmlFor="palette-search" className="sr-only">Search nodes</label>
        <input
          id="palette-search"
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search nodes…"
          className="w-full rounded-md border border-neutral-300 bg-transparent px-2 py-1.5 text-sm dark:border-neutral-700"
        />
        <p className="mt-1 text-xs text-neutral-600 dark:text-neutral-400">Drag onto the canvas, or click to add.</p>
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {groups.length === 0 && <p className="p-2 text-sm text-neutral-600">No node matches “{q}”.</p>}
        {groups.map(([cat, items]) => (
          <details key={cat} open={cat !== "app" || q !== ""} className="mb-2">
            <summary className="cursor-pointer py-1 text-xs font-semibold uppercase tracking-wide text-neutral-600 dark:text-neutral-400">
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
                    className="flex w-full items-center justify-between gap-2 rounded-md border border-neutral-200 px-2 py-1.5 text-left text-sm hover:bg-neutral-50 dark:border-neutral-800 dark:hover:bg-neutral-900"
                  >
                    <span className="truncate">{t.name}</span>
                    {t.risk !== "read" && !t.dynamic_risk && (
                      <span className={`text-[10px] font-medium uppercase ${t.risk === "destructive" ? "text-red-700 dark:text-red-400" : "text-amber-800 dark:text-amber-300"}`}>
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
