import { apiFetch } from "@/lib/api";
import type { Workflow, WorkflowNode } from "@/lib/workflow-schema";

export type JsonSchema = {
  type?: string | string[];
  enum?: unknown[];
  default?: unknown;
  description?: string;
  items?: JsonSchema;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  minimum?: number;
  maximum?: number;
};

export type NodeType = {
  type: string;
  name: string;
  category: string;
  description: string;
  parameters: { properties?: Record<string, JsonSchema>; required?: string[] };
  inputs: string[];
  outputs: string[];
  dynamic_outputs: boolean;
  risk: "read" | "write" | "destructive";
  dynamic_risk: boolean;
  icon: string | null;
  connector: string | null;
  needs_connection: boolean;
};

export type WorkflowSummary = {
  id: string;
  name: string;
  status: "draft" | "published";
  version: number;
  published_version: number | null;
  updated_at: string | null;
  node_count: number;
};

export type WorkflowMeta = { workflow: Workflow; published_version: number | null; updated_at: string | null };

/** One patch operation, as accepted by POST /api/workflows/{id}/patch. */
export type Operation = Record<string, unknown> & { op: string };

export type PatchResult = { workflow: Workflow; changes: unknown[]; risk: string };

export type Items = { json: unknown }[];
export type NodeRecord = {
  node_id: string;
  node_name: string;
  status: string;
  input: Record<string, Items> | null;
  output: Record<string, Items> | null;
  error: { message?: string } | null;
  duration_ms: number | null;
  attempts: number;
};
export type PendingApproval = { approval_id: string; [k: string]: unknown };
export type Execution = {
  execution: { id: string; status: string; mode: string; error: { message?: string } | null; cost_usd: number };
  nodes: NodeRecord[];
  pending_approvals?: PendingApproval[];
};
export type TestResult = {
  status?: string;
  output?: Record<string, Items> | null;
  error?: { message?: string } | null;
  needs_confirmation?: boolean;
  [k: string]: unknown;
};

export type Trigger = {
  node_id: string;
  type: "schedule" | "webhook";
  active: boolean;
  url?: string;
  has_secret?: boolean;
  secret_header?: string;
  next_run_at?: string | null;
  last_run_at?: string | null;
};

export type ConnectionLite = { id: string; provider: string; account_label: string | null; status: string };

const enc = encodeURIComponent;

export const workflowsApi = {
  nodeTypes: () => apiFetch<NodeType[]>("/api/node-types"),
  list: () => apiFetch<WorkflowSummary[]>("/api/workflows"),
  create: (name: string) =>
    apiFetch<{ workflow: Workflow }>("/api/workflows", { method: "POST", body: JSON.stringify({ name }) }),
  get: (id: string) => apiFetch<WorkflowMeta>(`/api/workflows/${enc(id)}`),
  patch: (id: string, baseVersion: number, operations: Operation[]) =>
    apiFetch<PatchResult>(`/api/workflows/${enc(id)}/patch`, {
      method: "POST",
      body: JSON.stringify({ base_version: baseVersion, operations }),
    }),
  publish: (id: string) =>
    apiFetch<{ workflow: Workflow; webhook_secrets?: Record<string, string> }>(`/api/workflows/${enc(id)}/publish`, {
      method: "POST",
    }),
  unpublish: (id: string) => apiFetch<{ workflow: Workflow }>(`/api/workflows/${enc(id)}/unpublish`, { method: "POST" }),
  remove: (id: string) => apiFetch<{ ok: boolean }>(`/api/workflows/${enc(id)}`, { method: "DELETE" }),
  run: (id: string, body: { trigger_node_id?: string; start_node_id?: string; trigger_data?: unknown } = {}) =>
    apiFetch<{ id: string; status: string }>(`/api/workflows/${enc(id)}/run`, { method: "POST", body: JSON.stringify(body) }),
  testNode: (id: string, nodeId: string, confirm = false) =>
    apiFetch<TestResult>(`/api/workflows/${enc(id)}/nodes/${enc(nodeId)}/test`, {
      method: "POST",
      body: JSON.stringify({ confirm }),
    }),
  execution: (executionId: string) => apiFetch<Execution>(`/api/executions/${enc(executionId)}`),
  decide: (approvalId: string, approve: boolean) =>
    apiFetch<unknown>(`/api/execution-approvals/${enc(approvalId)}/decision`, { method: "POST", body: JSON.stringify({ approve }) }),
  triggers: (id: string) => apiFetch<Trigger[]>(`/api/workflows/${enc(id)}/triggers`),
  rotateSecret: (id: string, nodeId: string) =>
    apiFetch<{ secret: string }>(`/api/workflows/${enc(id)}/triggers/${enc(nodeId)}/rotate-secret`, { method: "POST" }),
  connections: () => apiFetch<ConnectionLite[]>("/api/connections"),
};

/** Output handles of a node. The registry reports outputs for empty parameters; Switch grows with its rules. */
export function outputsFor(nt: NodeType | undefined, node: WorkflowNode): string[] {
  if (!nt) return ["main"];
  if (nt.type === "switch") {
    const p = node.parameters as { mode?: string; number_of_outputs?: number; rules?: unknown[]; fallback?: string };
    const n =
      p.mode === "expression" ? Math.max(1, Math.min(Number(p.number_of_outputs) || 2, 20)) : Math.max(1, p.rules?.length ?? 0);
    const outs = Array.from({ length: n }, (_, i) => `case_${i}`);
    return p.fallback === "extra" ? [...outs, "fallback"] : outs;
  }
  return nt.outputs;
}

export function uniqueName(base: string, existing: string[]): string {
  if (!existing.includes(base)) return base;
  let i = 2;
  while (existing.includes(`${base} ${i}`)) i++;
  return `${base} ${i}`;
}

export function newNodeId(): string {
  return `n_${Math.random().toString(36).slice(2, 10)}`;
}

/** The operation for dropping a node of `nt` on the canvas at `position`. */
export function addNodeOp(nt: NodeType, position: { x: number; y: number }, existingNames: string[]): Operation {
  return {
    op: "add_node",
    node: {
      id: newNodeId(),
      type: nt.type,
      name: uniqueName(nt.name.replace(/^.*?: /, ""), existingNames),
      parameters: {},
      position,
    },
  };
}

export const connectOp = (from: string, to: string, output: string, input: string): Operation => ({
  op: "connect", from, to, output, input,
});
export const disconnectOp = (from: string, to: string, output: string, input: string): Operation => ({
  op: "disconnect", from, to, output, input,
});
