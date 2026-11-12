import Ajv2020 from "ajv/dist/2020";

/** Workflow document, as defined by schemas/workflow.schema.json (shared with the API). */
export type WorkflowNode = {
  id: string;
  type: string;
  name: string;
  parameters: Record<string, unknown>;
  position: { x: number; y: number };
  connection_id?: string | null;
  settings?: Record<string, unknown>;
  pinned_data?: { json: Record<string, unknown> }[] | null;
  disabled?: boolean;
};
export type WorkflowEdge = { from: string; to: string; output: string; input?: string };
export type Workflow = {
  id: string;
  name: string;
  status: "draft" | "published";
  version: number;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  settings?: { auto_approve?: "off" | "writes" | "all"; error_workflow_id?: string | null; timeout_seconds?: number; cost_cap_usd?: number | null };
};

/** Compile the shared schema once (the API serves it at GET /api/workflow-schema). */
export function compileWorkflowValidator(schema: object) {
  const validate = new Ajv2020({ allErrors: true, strict: false }).compile(schema);
  return (doc: unknown): string[] =>
    validate(doc) ? [] : (validate.errors ?? []).map((e) => `${e.instancePath || "(root)"}: ${e.message}`);
}
