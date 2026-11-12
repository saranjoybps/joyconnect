import { createEvent, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: vi.fn() }));

// React Flow needs real layout (ResizeObserver, sizes) that jsdom lacks. The mock renders the nodes as buttons and
// exposes the callbacks the editor registers, so the tests drive the same handlers a real drag/connect/delete would.
type RFProps = {
  nodes: { id: string; position: { x: number; y: number }; data: { node: { name: string } } }[];
  onConnect: (c: unknown) => void;
  onDelete: (d: { nodes: unknown[]; edges: unknown[] }) => void;
  onNodeDragStop: (e: unknown, n: unknown) => void;
  onNodeClick: (e: unknown, n: unknown) => void;
};
let rf: RFProps;
vi.mock("@xyflow/react", () => ({
  ReactFlowProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useReactFlow: () => ({ screenToFlowPosition: (p: { x: number; y: number }) => ({ x: p.x + 1000, y: p.y + 1000 }) }),
  ReactFlow: (props: RFProps) => {
    rf = props;
    return (
      <div data-testid="flow">
        {props.nodes.map((n) => (
          <button key={n.id} onClick={() => props.onNodeClick({}, n)}>{`canvas:${n.data.node.name}`}</button>
        ))}
      </div>
    );
  },
  Background: () => null, Controls: () => null, MiniMap: () => null, Handle: () => null,
  Position: { Left: "left", Right: "right" },
  applyNodeChanges: (_c: unknown, n: unknown) => n,
}));

import { WorkflowEditor } from "@/components/canvas/WorkflowEditor";
import { ApiError } from "@/lib/api";
import type { Workflow } from "@/lib/workflow-schema";
import { workflowsApi, type NodeType } from "@/lib/workflows";

const nt = (over: Partial<NodeType> & { type: string; name: string }): NodeType => ({
  category: "data", description: "", parameters: { properties: {}, required: [] }, inputs: ["main"], outputs: ["main"],
  dynamic_outputs: false, risk: "read", dynamic_risk: false, icon: null, connector: null, needs_connection: false, ...over,
});
const TYPES: NodeType[] = [
  nt({ type: "manual_trigger", name: "Manual Trigger", category: "trigger", inputs: [] }),
  nt({ type: "schedule_trigger", name: "Schedule Trigger", category: "trigger", inputs: [],
    parameters: { properties: { timezone: { type: "string" }, rules: { type: "array" } }, required: ["rules"] } }),
  nt({ type: "webhook_trigger", name: "Webhook", category: "trigger", inputs: [] }),
  nt({ type: "if", name: "IF", category: "flow", outputs: ["true", "false"] }),
  nt({ type: "set", name: "Edit Fields (Set)", parameters: { properties: { mode: { enum: ["manual", "json"] }, note: { type: "string" }, count: { type: "integer" } }, required: [] } }),
  nt({ type: "slack__post_message", name: "Slack: Post message", category: "app", risk: "write", connector: "slack", needs_connection: true,
    parameters: { properties: { channel: { type: "string" } }, required: ["channel"] } }),
];

const wf = (over: Partial<Workflow> = {}): Workflow => ({
  id: "w1", name: "Report", status: "draft", version: 4, settings: {},
  nodes: [
    { id: "t", type: "manual_trigger", name: "Start", parameters: {}, position: { x: 0, y: 0 } },
    { id: "s", type: "set", name: "Make", parameters: {}, position: { x: 240, y: 0 } },
  ],
  edges: [{ from: "t", to: "s", output: "main", input: "main" }],
  ...over,
});

function setup(doc: Workflow = wf(), published: number | null = null) {
  vi.spyOn(workflowsApi, "nodeTypes").mockResolvedValue(TYPES);
  vi.spyOn(workflowsApi, "get").mockResolvedValue({ workflow: doc, published_version: published, updated_at: null });
  vi.spyOn(workflowsApi, "triggers").mockResolvedValue([]);
  vi.spyOn(workflowsApi, "connections").mockResolvedValue([
    { id: "c1", provider: "slack", account_label: "Acme Slack", status: "active" },
  ]);
  let version = doc.version;
  const patch = vi.spyOn(workflowsApi, "patch").mockImplementation(async (_id, base, ops) => {
    expect(base).toBe(version);                      // every call carries the latest version
    version += 1;
    return { workflow: { ...doc, version }, changes: ops, risk: "low" };
  });
  return { patch };
}

beforeEach(() => vi.spyOn(window, "confirm").mockReturnValue(true));
afterEach(() => vi.restoreAllMocks());

async function ready() {
  render(<WorkflowEditor id="w1" />);
  await screen.findByText("canvas:Start");
  await screen.findByRole("button", { name: /Manual Trigger/ });
}

describe("palette", () => {
  it("is generated from the node registry, grouped, and searchable", async () => {
    setup();
    await ready();
    expect(screen.getByText("Triggers")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Slack: Post message/ })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Search nodes"), "webhook");
    expect(screen.getByRole("button", { name: /Webhook/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^IF/ })).toBeNull();
  });

  it("clicking a node adds it with an add_node patch carrying the base version", async () => {
    const { patch } = setup();
    await ready();
    await userEvent.click(screen.getByRole("button", { name: /^IF/ }));
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    const [id, base, ops] = patch.mock.calls[0];
    expect(id).toBe("w1");
    expect(base).toBe(4);
    expect(ops).toHaveLength(1);
    expect(ops[0]).toMatchObject({ op: "add_node", node: { type: "if", name: "IF", parameters: {} } });
  });

  it("dropping a node places it at the drop position and names it uniquely", async () => {
    const { patch } = setup();
    await ready();
    const area = screen.getByTestId("flow").parentElement!;
    const data: Record<string, string> = { "application/x-workflow-node": "set" };
    const drop = createEvent.drop(area, { dataTransfer: { getData: (k: string) => data[k] } });
    Object.defineProperty(drop, "clientX", { value: 20 });   // jsdom has no DragEvent, so add the coordinates by hand
    Object.defineProperty(drop, "clientY", { value: 30 });
    fireEvent(area, drop);
    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch.mock.calls[0][2][0]).toMatchObject({
      op: "add_node", node: { type: "set", name: "Edit Fields (Set)", position: { x: 1020, y: 1030 } },
    });
  });
});

describe("canvas edits go through the patch API", () => {
  it("connect → connect op with source and target handles", async () => {
    const { patch } = setup();
    await ready();
    rf.onConnect({ source: "s", target: "t", sourceHandle: "true", targetHandle: "main" });
    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch.mock.calls[0][2]).toEqual([{ op: "connect", from: "s", to: "t", output: "true", input: "main" }]);
  });

  it("deleting an edge → disconnect op", async () => {
    const { patch } = setup();
    await ready();
    rf.onDelete({ nodes: [], edges: [{ source: "t", target: "s", sourceHandle: "main", targetHandle: "main" }] });
    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch.mock.calls[0][2]).toEqual([{ op: "disconnect", from: "t", to: "s", output: "main", input: "main" }]);
  });

  it("deleting a node → remove_node only (its edges go with it, no separate disconnect)", async () => {
    const { patch } = setup();
    await ready();
    rf.onDelete({ nodes: [{ id: "s" }], edges: [{ source: "t", target: "s", sourceHandle: "main", targetHandle: "main" }] });
    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch.mock.calls[0][2]).toEqual([{ op: "remove_node", id: "s" }]);
  });

  it("deleting a node of a published workflow asks first, and cancel changes nothing", async () => {
    const { patch } = setup(wf({ status: "published" }), 4);
    vi.spyOn(window, "confirm").mockReturnValue(false);
    await ready();
    rf.onDelete({ nodes: [{ id: "s" }], edges: [] });
    await new Promise((r) => setTimeout(r, 20));
    expect(window.confirm).toHaveBeenCalled();
    expect(patch).not.toHaveBeenCalled();
  });

  it("dragging a node → move op with rounded position", async () => {
    const { patch } = setup();
    await ready();
    rf.onNodeDragStop({}, { id: "s", position: { x: 300.4, y: 99.6 } });
    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch.mock.calls[0][2]).toEqual([{ op: "move", id: "s", position: { x: 300, y: 100 } }]);
  });

  it("consecutive edits are sent one after another, each on the newest version", async () => {
    const { patch } = setup();
    await ready();
    rf.onNodeDragStop({}, { id: "s", position: { x: 1, y: 1 } });
    rf.onNodeDragStop({}, { id: "t", position: { x: 2, y: 2 } });
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(2));
    expect(patch.mock.calls.map((c) => c[1])).toEqual([4, 5]);
  });

  it("a conflict reloads the latest document and tells the user", async () => {
    setup();
    vi.spyOn(workflowsApi, "patch").mockRejectedValue(
      new ApiError(409, "The workflow changed since you loaded it.", { current: wf({ version: 9, name: "Changed elsewhere" }) }),
    );
    await ready();
    rf.onNodeDragStop({}, { id: "s", position: { x: 1, y: 1 } });
    expect(await screen.findByText(/changed somewhere else/, {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByLabelText("Workflow name")).toHaveValue("Changed elsewhere");
  });

  it("a rejected edit shows the server's reason", async () => {
    setup();
    vi.spyOn(workflowsApi, "patch").mockRejectedValue(new ApiError(422, "duplicate node name 'Make'", { errors: ["duplicate node name 'Make'"] as never }));
    await ready();
    rf.onConnect({ source: "t", target: "s", sourceHandle: "main", targetHandle: "main" });
    expect(await screen.findByRole("alert")).toHaveTextContent("duplicate node name");
  });

  it("renaming the workflow sends a rename op without a node id", async () => {
    const { patch } = setup();
    await ready();
    const input = screen.getByLabelText("Workflow name");
    await userEvent.clear(input);
    await userEvent.type(input, "Weekly report");
    fireEvent.blur(input);
    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch.mock.calls[0][2]).toEqual([{ op: "rename", name: "Weekly report" }]);
  });
});

describe("config panel", () => {
  it("editing a parameter sends update_node with only that key; numbers are numbers, expressions stay text", async () => {
    const { patch } = setup();
    await ready();
    await userEvent.click(screen.getByText("canvas:Make"));
    const panel = screen.getByRole("complementary", { name: "Configure Make" });
    const count = within(panel).getByLabelText("count");
    await userEvent.type(count, "5");
    fireEvent.blur(count);
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    expect(patch.mock.calls[0][2]).toEqual([{ op: "update_node", id: "s", parameters: { count: 5 } }]);

    const note = within(panel).getByLabelText("note");
    fireEvent.change(note, { target: { value: "{{ $json.x }}" } });
    fireEvent.blur(note);
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(2));
    expect(patch.mock.calls[1][2]).toEqual([{ op: "update_node", id: "s", parameters: { note: "{{ $json.x }}" } }]);
  });

  it("choosing a select value saves immediately", async () => {
    const { patch } = setup();
    await ready();
    await userEvent.click(screen.getByText("canvas:Make"));
    await userEvent.selectOptions(screen.getByLabelText("mode"), "json");
    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch.mock.calls[0][2]).toEqual([{ op: "update_node", id: "s", parameters: { mode: "json" } }]);
  });

  it("an app node asks which connected account to use and saves connection_id", async () => {
    const doc = wf({ nodes: [{ id: "a", type: "slack__post_message", name: "Post", parameters: {}, position: { x: 0, y: 0 } }], edges: [] });
    const { patch } = setup(doc);
    render(<WorkflowEditor id="w1" />);
    await userEvent.click(await screen.findByText("canvas:Post"));
    await userEvent.selectOptions(await screen.findByLabelText(/Account/), "c1");
    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch.mock.calls[0][2]).toEqual([{ op: "update_node", id: "a", connection_id: "c1" }]);
  });

  it("Test node shows real output; a write node needs an explicit confirmation first", async () => {
    const doc = wf({ nodes: [{ id: "a", type: "slack__post_message", name: "Post", parameters: { channel: "#x" }, position: { x: 0, y: 0 } }], edges: [] });
    setup(doc);
    const test = vi.spyOn(workflowsApi, "testNode")
      .mockRejectedValueOnce(new ApiError(409, "Slack: Post message changes data in the connected app.", { requires_confirmation: true }))
      .mockResolvedValueOnce({ status: "success", output: { main: [{ json: { ts: "1700.1", ok: true } }] }, error: null });
    render(<WorkflowEditor id="w1" />);
    await userEvent.click(await screen.findByText("canvas:Post"));
    await userEvent.click(screen.getByRole("button", { name: "Test node" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("changes data");
    expect(test).toHaveBeenCalledWith("w1", "a", false);
    await userEvent.click(screen.getByRole("button", { name: "Run it for real" }));
    expect(await screen.findByText(/"ts": "1700.1"/)).toBeInTheDocument();
    expect(test).toHaveBeenLastCalledWith("w1", "a", true);
  });

  it("shows a node's error from a test", async () => {
    setup();
    vi.spyOn(workflowsApi, "testNode").mockResolvedValue({ status: "error", output: null, error: { message: "Slack said channel_not_found" } });
    await ready();
    await userEvent.click(screen.getByText("canvas:Make"));
    await userEvent.click(screen.getByRole("button", { name: "Test node" }));
    expect(await screen.findByText(/channel_not_found/)).toBeInTheDocument();
  });
});

describe("schedule trigger settings", () => {
  const sched = () => wf({
    nodes: [{ id: "x", type: "schedule_trigger", name: "Every", position: { x: 0, y: 0 },
      parameters: { timezone: "UTC", rules: [{ interval: "minutes", every: 5 }] } }],
    edges: [],
  });

  it("shows the rule in words and saves interval changes as a whole rules array", async () => {
    const { patch } = setup(sched());
    render(<WorkflowEditor id="w1" />);
    await userEvent.click(await screen.findByText("canvas:Every"));
    expect(screen.getByText("Every 5 minutes")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Rule 1 interval"), "days");
    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch.mock.calls[0][2]).toEqual([{ op: "update_node", id: "x",
      parameters: { timezone: "UTC", rules: [{ interval: "days", every: 5 }] } }]);
  });

  it("adds a cron rule and a second rule", async () => {
    const { patch } = setup(sched());
    render(<WorkflowEditor id="w1" />);
    await userEvent.click(await screen.findByText("canvas:Every"));
    await userEvent.click(screen.getByRole("button", { name: "Add rule" }));
    await waitFor(() => expect(patch).toHaveBeenCalled());
    const rules = (patch.mock.calls[0][2][0] as unknown as { parameters: { rules: unknown[] } }).parameters.rules;
    expect(rules).toHaveLength(2);
    expect(rules[1]).toMatchObject({ interval: "days", hour: 9 });
  });
});

describe("publish and run", () => {
  it("the Draft/Published switch publishes, and unpublishes", async () => {
    setup();
    const publish = vi.spyOn(workflowsApi, "publish").mockResolvedValue({ workflow: wf({ status: "published", version: 4 }) });
    const unpublish = vi.spyOn(workflowsApi, "unpublish").mockResolvedValue({ workflow: wf() });
    await ready();
    const sw = screen.getByRole("switch", { name: "Published" });
    expect(sw).toHaveAttribute("aria-checked", "false");
    expect(sw).toHaveTextContent("Draft");
    await userEvent.click(sw);
    await waitFor(() => expect(publish).toHaveBeenCalledWith("w1"));
    await waitFor(() => expect(screen.getByRole("switch", { name: "Published" })).toHaveAttribute("aria-checked", "true"));
    await userEvent.click(screen.getByRole("switch", { name: "Published" }));
    await waitFor(() => expect(unpublish).toHaveBeenCalledWith("w1"));
    await waitFor(() => expect(screen.getByRole("switch", { name: "Published" })).toHaveAttribute("aria-checked", "false"));
  });

  it("explains why a workflow cannot be published and shows a generated webhook secret once", async () => {
    setup();
    const publish = vi.spyOn(workflowsApi, "publish")
      .mockRejectedValueOnce(new ApiError(422, "This workflow is not ready to publish", { errors: ["node 'Make': parameter 'x' is required", "add a trigger"] as never }))
      .mockResolvedValueOnce({ workflow: wf({ status: "published" }), webhook_secrets: { t: "s3cr3t-value" } });
    await ready();
    await userEvent.click(screen.getByRole("switch", { name: "Published" }));
    expect(await screen.findByText(/parameter 'x' is required/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("switch", { name: "Published" }));
    expect(await screen.findByText("s3cr3t-value")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "I copied it" }));
    expect(screen.queryByText("s3cr3t-value")).toBeNull();
    expect(publish).toHaveBeenCalledTimes(2);
  });

  it("Run workflow starts at the Manual trigger and shows each node's result", async () => {
    setup();
    const run = vi.spyOn(workflowsApi, "run").mockResolvedValue({ id: "e1", status: "queued" });
    vi.spyOn(workflowsApi, "execution").mockResolvedValue({
      execution: { id: "e1", status: "success", mode: "manual", error: null, cost_usd: 0 },
      nodes: [
        { node_id: "t", node_name: "Start", status: "success", input: null, output: { main: [{ json: {} }] }, error: null, duration_ms: 3, attempts: 1 },
        { node_id: "s", node_name: "Make", status: "success", input: null, output: { main: [{ json: { a: 1 } }] }, error: null, duration_ms: 5, attempts: 1 },
      ],
    });
    await ready();
    await userEvent.click(screen.getByRole("button", { name: "Run workflow" }));
    const region = await screen.findByRole("region", { name: "Run result" });
    expect(region).toHaveTextContent("Run success");
    expect(region).toHaveTextContent("Make — success · 5 ms");
    expect(run).toHaveBeenCalledWith("w1", { trigger_node_id: "t", trigger_data: undefined });
  });

  it("a run waiting for approval offers Approve and Reject", async () => {
    setup();
    vi.spyOn(workflowsApi, "run").mockResolvedValue({ id: "e1", status: "queued" });
    vi.spyOn(workflowsApi, "execution").mockResolvedValue({
      execution: { id: "e1", status: "waiting", mode: "manual", error: null, cost_usd: 0 }, nodes: [],
      pending_approvals: [{ approval_id: "ap1", node_name: "Post", connector_name: "Slack: Post message" }],
    });
    const decide = vi.spyOn(workflowsApi, "decide").mockResolvedValue({});
    await ready();
    await userEvent.click(screen.getByRole("button", { name: "Run workflow" }));
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect(decide).toHaveBeenCalledWith("ap1", true);
  });

  it("refuses to run a workflow without a trigger", async () => {
    setup(wf({ nodes: [], edges: [] }));
    const run = vi.spyOn(workflowsApi, "run");
    render(<WorkflowEditor id="w1" />);
    await screen.findByText(/Drag a node from the palette/);
    await userEvent.click(screen.getByRole("button", { name: "Run workflow" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Add a trigger node");
    expect(run).not.toHaveBeenCalled();
  });
});
