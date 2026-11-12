"use client";

import type { ReactNode } from "react";
import { LogoTile } from "@/components/pro/ui";
import type { LucideIcon } from "lucide-react";

export type NodeStatus = "idle" | "running" | "ok" | "error";

const DOT: Record<NodeStatus, string> = {
  idle: "bg-p-muted/50", running: "bg-p-accent-text", ok: "bg-p-ok", error: "bg-p-bad",
};

/** Slim workflow node: small logo tile (full colour for apps, our own icon for core nodes), name, kind, status dot. */
export function WorkflowNode({ name, kind, logo, icon: Icon, status = "idle", selected, risk, className = "", style }: {
  name: string; kind: string; logo?: ReactNode; icon?: LucideIcon; status?: NodeStatus; selected?: boolean;
  risk?: "write" | "destructive"; className?: string; style?: React.CSSProperties;
}) {
  return (
    <div style={style}
      className={`relative flex w-48 items-center gap-2.5 rounded-lg border bg-p-surface px-2.5 py-2 transition-shadow duration-150 ${selected ? "border-p-accent shadow-[0_0_0_1px_var(--p-accent),0_0_22px_-4px_var(--p-accent)]" : "border-p-line-strong shadow-[var(--p-shadow)]"} ${className}`}>
      {logo ? <LogoTile size={26}>{logo}</LogoTile> : (
        <span className="flex size-[26px] shrink-0 items-center justify-center rounded-md bg-p-accent-soft text-p-accent-text">
          {Icon && <Icon size={14} strokeWidth={1.75} aria-hidden />}
        </span>
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-medium leading-4 text-p-text">{name}</p>
        <p className="truncate text-[11px] leading-4 text-p-muted">{kind}</p>
      </div>
      {risk && <span className={`text-[10px] font-semibold uppercase ${risk === "destructive" ? "text-p-bad" : "text-p-warn"}`}>{risk}</span>}
      <span role="img" aria-label={`status: ${status}`} className={`size-1.5 shrink-0 rounded-full ${DOT[status]} ${status === "running" ? "animate-pulse" : ""}`} />
      <span aria-hidden className="absolute -left-[3px] size-1.5 rounded-full border border-p-line-strong bg-p-surface-3" />
    </div>
  );
}

/** Dotted-grid canvas with thin connection lines; the line into a running node flows. */
export function CanvasPreview({ nodes, running }: {
  nodes: { id: string; x: number; y: number; node: ReactNode }[]; running?: string;
}) {
  const W = 192, H = 46;
  const edges = nodes.slice(1).map((n, i) => ({ from: nodes[i], to: n }));
  return (
    <div className="p-dots relative h-64 overflow-hidden rounded-xl border border-p-line">
      <svg aria-hidden className="absolute inset-0 size-full">
        {edges.map(({ from, to }) => {
          const x1 = from.x + W, y1 = from.y + H / 2, x2 = to.x, y2 = to.y + H / 2;
          const mx = (x1 + x2) / 2;
          const d = `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
          const flowing = running === to.id;
          return (
            <g key={`${from.id}-${to.id}`}>
              <path d={d} fill="none" stroke="var(--p-line-strong)" strokeWidth="1.25" />
              {flowing && <path d={d} fill="none" stroke="var(--p-accent-text)" strokeWidth="1.5" className="p-flow" />}
            </g>
          );
        })}
      </svg>
      {nodes.map((n) => (
        <div key={n.id} className="absolute" style={{ left: n.x, top: n.y }}>{n.node}</div>
      ))}
    </div>
  );
}
