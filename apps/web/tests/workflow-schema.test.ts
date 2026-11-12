import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { compileWorkflowValidator, type Workflow } from "@/lib/workflow-schema";

// The very file the API validates against.
const schema = JSON.parse(readFileSync(resolve(__dirname, "../../../schemas/workflow.schema.json"), "utf-8"));
const validate = compileWorkflowValidator(schema);

const ok: Workflow = {
  id: "w1", name: "Leads", status: "draft", version: 1, settings: { auto_approve: "off" },
  nodes: [{ id: "t", type: "manual_trigger", name: "Start", parameters: {}, position: { x: 0, y: 0 } }],
  edges: [],
};

describe("shared workflow schema (web side)", () => {
  it("accepts a valid workflow", () => expect(validate(ok)).toEqual([]));
  it("rejects what the API rejects", () => {
    expect(validate({ ...ok, status: "live" }).length).toBeGreaterThan(0);
    expect(validate({ ...ok, extra: 1 }).length).toBeGreaterThan(0);
    expect(validate({ ...ok, nodes: [{ ...ok.nodes[0], id: "bad id!" }] }).length).toBeGreaterThan(0);
    expect(validate({ id: "x" }).length).toBeGreaterThan(0);
    expect(validate({ ...ok, settings: { auto_approve: "sometimes" } }).length).toBeGreaterThan(0);
  });
});
