"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { CanvasNodeData } from "@/lib/canvas";

const STATUS: Record<string, string> = {
  success: "bg-emerald-500",
  error: "bg-red-500",
  waiting: "bg-amber-500",
  running: "bg-sky-500",
  skipped: "bg-neutral-400",
};

/** A node on the canvas: one input handle per input, one output handle per output (IF has true/false, Switch has cases). */
export function NodeCard({ data, selected }: NodeProps) {
  const { node, nodeType, outputs, inputs, status } = data as CanvasNodeData;
  const risk = nodeType?.risk;
  return (
    <div
      data-testid={`node-${node.id}`}
      className={`min-w-44 rounded-lg border bg-white px-3 py-2 text-sm shadow-sm dark:bg-neutral-900 ${selected ? "border-sky-500 ring-2 ring-sky-300" : "border-neutral-300 dark:border-neutral-700"} ${node.disabled ? "opacity-50" : ""}`}
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
        {status && <span aria-label={`last run: ${status}`} className={`size-2 rounded-full ${STATUS[status] ?? "bg-neutral-400"}`} />}
        <span className="font-medium">{node.name}</span>
        {risk && risk !== "read" && (
          <span className={`text-[10px] font-semibold uppercase ${risk === "destructive" ? "text-red-700" : "text-amber-700"}`}>{risk}</span>
        )}
      </div>
      <div className="text-xs text-neutral-600 dark:text-neutral-400">{nodeType?.name ?? node.type}</div>
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
        <div className="mt-1 flex justify-end gap-2 text-[10px] text-neutral-600 dark:text-neutral-400">
          {outputs.map((o) => <span key={o}>{o}</span>)}
        </div>
      )}
    </div>
  );
}
