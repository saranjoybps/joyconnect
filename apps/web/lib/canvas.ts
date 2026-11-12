import type { Workflow, WorkflowNode } from "@/lib/workflow-schema";
import { outputsFor, type NodeType } from "@/lib/workflows";

export const MAIN = "main";

export type CanvasNodeData = {
  node: WorkflowNode;
  nodeType: NodeType | undefined;
  outputs: string[];
  inputs: string[];
  status?: string;
};

export const edgeKey = (e: { from: string; to: string; output: string; input?: string }) =>
  `${e.from}:${e.output}->${e.to}:${e.input ?? MAIN}`;

/** Workflow nodes as React Flow nodes. */
export function toFlowNodes(wf: Workflow, types: Map<string, NodeType>, status: Record<string, string> = {}) {
  return wf.nodes.map((n) => {
    const nt = types.get(n.type);
    const data: CanvasNodeData = {
      node: n,
      nodeType: nt,
      outputs: outputsFor(nt, n),
      inputs: nt?.inputs ?? [MAIN],
      status: status[n.id],
    };
    return { id: n.id, type: "workflowNode", position: n.position, data, selected: undefined as boolean | undefined };
  });
}

export function toFlowEdges(wf: Workflow) {
  return wf.edges.map((e) => ({
    id: edgeKey(e),
    source: e.from,
    target: e.to,
    sourceHandle: e.output,
    targetHandle: e.input ?? MAIN,
    label: e.output === MAIN ? undefined : e.output,
  }));
}

/** Where to put the Nth node added by a click rather than a drop: a staggered grid right of the existing nodes. */
export function nextPosition(wf: Workflow): { x: number; y: number } {
  if (!wf.nodes.length) return { x: 80, y: 120 };
  const maxX = Math.max(...wf.nodes.map((n) => n.position.x));
  const last = wf.nodes[wf.nodes.length - 1];
  return { x: maxX + 240, y: last.position.y };
}

/** The trigger "Run workflow" should start from: Manual first, else the first trigger node. */
export function pickRunTrigger(wf: Workflow, types: Map<string, NodeType>): WorkflowNode | undefined {
  const triggers = wf.nodes.filter((n) => types.get(n.type)?.category === "trigger" && !n.disabled);
  return triggers.find((n) => n.type === "manual_trigger") ?? triggers[0];
}

export function sampleTriggerData(type: string): unknown {
  if (type === "schedule_trigger") return { timestamp: new Date().toISOString() };
  if (type === "webhook_trigger") return { headers: {}, params: {}, query: {}, body: {} };
  return undefined;
}
