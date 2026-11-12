"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { CanvasNodeData } from "@/lib/canvas";

const STATUS: Record<string, string> = {
  success: "bg-m-ok",
  error: "bg-m-bad",
  waiting: "bg-m-warn",
  running: "bg-m-info",
  skipped: "bg-m-muted",
};

/** A node on the canvas: one input handle per input, one output handle per output (IF has true/false, Switch has cases). */
export function NodeCard({ data, selected }: NodeProps) {
  const { node, nodeType, outputs, inputs, status } = data as CanvasNodeData;
  const risk = nodeType?.risk;
  return (
    <div
      data-testid={`node-${node.id}`}
      className={`border border-m-line bg-m-panel shadow-[var(--m-shadow)] min-w-40 rounded-xl px-3 py-2 text-[13px] ${selected ? "border-m-text ring-2 ring-m-accent/30" : ""} ${node.disabled ? "opacity-50" : ""}`}
    >
      {inputs.map((name, i) => (
        <Handle
          key={name}
          id={name}
          type="target"
          position={Position.Left}
          style={{ top: inputs.length === 1 ? "50%" : `${((i + 1) * 100) / (inputs.length + 1)}%` }}
          title={name}
        />
      ))}
      <div className="flex items-center gap-2">
        {status && <span aria-label={`last run: ${status}`} className={`size-2 rounded-full ${STATUS[status] ?? "bg-m-muted"}`} />}
        <span className="font-medium">{node.name}</span>
        {risk && risk !== "read" && (
          <span className={`text-[10px] font-semibold uppercase ${risk === "destructive" ? "text-m-bad" : "text-m-warn"}`}>{risk}</span>
        )}
      </div>
      <div className="text-xs text-m-muted">{nodeType?.name ?? node.type}</div>
      {outputs.map((name, i) => (
        <Handle
          key={name}
          id={name}
          type="source"
          position={Position.Right}
          style={{ top: outputs.length === 1 ? "50%" : `${((i + 1) * 100) / (outputs.length + 1)}%` }}
          title={name}
        />
      ))}
      {outputs.length > 1 && (
        <div className="mt-1 flex justify-end gap-2 text-[10px] text-m-muted">
          {outputs.map((o) => <span key={o}>{o}</span>)}
        </div>
      )}
    </div>
  );
}
