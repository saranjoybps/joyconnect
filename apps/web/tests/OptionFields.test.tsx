import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: vi.fn() }));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));

import { ConfigPanel } from "@/components/canvas/ConfigPanel";
import { buildMapped, joinRange, splitRange } from "@/components/canvas/OptionFields";
import { ApiError, apiFetch } from "@/lib/api";
import { clearOptionsCache, dependentsOf, idFromUrl, optionsApi, OPTIONS_TTL_MS, type Option, type UiSpec } from "@/lib/options";
import type { Workflow, WorkflowNode } from "@/lib/workflow-schema";
import { workflowsApi, type JsonSchema, type NodeType } from "@/lib/workflows";

const URL_PATTERN = "/d/([A-Za-z0-9_-]{20,})";
const SS: UiSpec = { kind: "locator", loader: "spreadsheets", modes: ["list", "url", "id"], url_pattern: URL_PATTERN };
const TAB: UiSpec = { kind: "range", loader: "tabs", depends_on: ["spreadsheet_id"] };
const COLS: UiSpec = { kind: "columns", loader: "columns", depends_on: ["spreadsheet_id", "range"], output: "array" };

const str = (ui?: UiSpec): JsonSchema => ({ type: "string", ...(ui ? { "x-ui": ui } : {}) });
const nt = (type: string, resource: string, operation: string, properties: Record<string, JsonSchema>): NodeType => ({
  type, name: `Google Sheets: ${operation}`, category: "app", description: "d", inputs: ["main"], outputs: ["main"],
  dynamic_outputs: false, risk: "write", dynamic_risk: false, icon: null, connector: "google_sheets", needs_connection: true,
  resource, operation, parameters: { properties, required: Object.keys(properties) },
});

const APPEND = nt("google_sheets__append_row", "Row", "Append", {
  spreadsheet_id: str(SS), range: str(TAB), values: { type: "array", "x-ui": COLS },
});
const GET = nt("google_sheets__get_values", "Value", "Get", { spreadsheet_id: str(SS), range: str(TAB) });
const LIST_TABS = nt("google_sheets__list_tabs", "Tab", "List", { spreadsheet_id: str(SS) });
const UPDATE = nt("google_sheets__update_values", "Row", "Update", { spreadsheet_id: str(SS), range: str(TAB) });
const SIBLINGS = [APPEND, UPDATE, GET, LIST_TABS];

const workflow = { id: "w", name: "w", status: "draft", version: 1, nodes: [], edges: [], settings: {} } as unknown as Workflow;
const node = (over: Partial<WorkflowNode> = {}): WorkflowNode => ({
  id: "n1", type: APPEND.type, name: "Add row", position: { x: 0, y: 0 }, connection_id: "c1", parameters: {}, ...over,
} as WorkflowNode);

const FILES: Option[] = [
  { value: "1LeadsAbCdEfGhIjKlMnOpQrStUv01", name: "Test Leads", description: "Edited 2026-11-01" },
  { value: "1SalesAbCdEfGhIjKlMnOpQrStUv02", name: "Sales 2026" },
];

let onApply: ReturnType<typeof vi.fn>;
let load: ReturnType<typeof vi.spyOn>;

function panel(n: WorkflowNode, type: NodeType = APPEND) {
  return render(
    <ConfigPanel
      workflowId="w" workflow={workflow} node={n} nodeType={type} siblings={SIBLINGS} published={false}
      lastRun={undefined} triggers={[]} onApply={onApply as never} onDeleteNode={vi.fn()} onTested={vi.fn()}
    />,
  );
}

beforeEach(() => {
  clearOptionsCache();
  onApply = vi.fn().mockResolvedValue(true);
  vi.spyOn(workflowsApi, "connections").mockResolvedValue([
    { id: "c1", provider: "google_sheets", account_label: "sam@x.com", status: "active" },
    { id: "c2", provider: "google_sheets", account_label: "work@x.com", status: "active" },
  ]);
  load = vi.spyOn(optionsApi, "load").mockImplementation(async (_t, req) => {
    const r = req as { parameter: string };
    if (r.parameter === "spreadsheet_id") return { options: FILES, cached: false, loader: "spreadsheets" };
    if (r.parameter === "range") return { options: [{ value: "Sheet1", name: "Sheet1" }, { value: "Q4 data", name: "Q4 data" }], cached: false, loader: "tabs" };
    return { options: [{ value: "Name", name: "Name", description: "Column A" }, { value: "Email", name: "Email", description: "Column B" }], cached: false, loader: "columns" };
  });
});
afterEach(() => vi.restoreAllMocks());

const callsFor = (parameter: string) => load.mock.calls.filter((c: unknown[]) => (c[1] as { parameter: string }).parameter === parameter);

describe("field order", () => {
  it("shows Account, then Resource, then Operation, then the dependent fields", async () => {
    panel(node());
    await screen.findByLabelText(/Account/);
    const all = Array.from(document.querySelectorAll("label")).map((l) => l.textContent?.replace(/[\s*]+$/, "").trim());
    const idx = (t: string) => all.findIndex((x) => x?.toLowerCase().startsWith(t));
    expect(idx("account")).toBeLessThan(idx("resource"));
    expect(idx("resource")).toBeLessThan(idx("operation"));
    expect(idx("operation")).toBeLessThan(idx("spreadsheet id"));
    expect(idx("spreadsheet id")).toBeLessThan(idx("range"));
    expect(idx("range")).toBeLessThan(idx("values"));
  });

  it("switches the operation and the resource, keeping the same app", async () => {
    panel(node());
    const operation = await screen.findByLabelText("Operation");
    expect(Array.from(operation.querySelectorAll("option")).map((o) => o.textContent)).toEqual(["Append", "Update"]);
    await userEvent.selectOptions(operation, UPDATE.type);
    expect(onApply).toHaveBeenLastCalledWith([{ op: "update_node", id: "n1", type: UPDATE.type }]);
    await userEvent.selectOptions(screen.getByLabelText("Resource"), "Value");
    expect(onApply).toHaveBeenLastCalledWith([{ op: "update_node", id: "n1", type: GET.type }]);
    await userEvent.selectOptions(screen.getByLabelText("Resource"), "Tab");
    expect(onApply).toHaveBeenLastCalledWith([{ op: "update_node", id: "n1", type: LIST_TABS.type }]);
  });
});

describe("resource locator", () => {
  it("lists spreadsheets from the account and saves the id; children are cleared", async () => {
    panel(node({ parameters: { spreadsheet_id: "old", range: "Sheet1!A:B", values: ["a", "b"] } }));
    const select = await screen.findByRole("combobox", { name: /spreadsheet id/i });
    await waitFor(() => expect(within(select).getByText(/Test Leads/)).toBeInTheDocument());
    await userEvent.selectOptions(select, FILES[0].value as string);
    expect(onApply).toHaveBeenLastCalledWith([{
      op: "update_node", id: "n1", parameters: { spreadsheet_id: FILES[0].value }, remove_parameters: ["range", "values"],
    }]);
    expect(callsFor("spreadsheet_id")[0][1]).toMatchObject({ connection_id: "c1", parameter: "spreadsheet_id" });
  });

  it("By URL extracts the id; a bad link is refused", async () => {
    panel(node());
    await userEvent.click(await screen.findByRole("button", { name: "By URL" }));
    const input = screen.getByPlaceholderText("Paste the link");
    await userEvent.type(input, "https://docs.google.com/spreadsheets/d/1LeadsAbCdEfGhIjKlMnOpQrStUv01/edit#gid=0");
    await userEvent.tab();
    expect(onApply).toHaveBeenLastCalledWith([{ op: "update_node", id: "n1", parameters: { spreadsheet_id: "1LeadsAbCdEfGhIjKlMnOpQrStUv01" } }]);
    onApply.mockClear();
    await userEvent.clear(input);
    await userEvent.type(input, "not a link");
    await userEvent.tab();
    expect(await screen.findByRole("alert")).toHaveTextContent(/does not look right/);
    expect(onApply).not.toHaveBeenCalled();
  });

  it("By ID accepts an id or an expression", async () => {
    panel(node());
    await userEvent.click(await screen.findByRole("button", { name: "By ID" }));
    await userEvent.type(screen.getByPlaceholderText(/ID or/), "{{{{ $json.sheet }}");
    await userEvent.tab();
    expect(onApply).toHaveBeenLastCalledWith([{ op: "update_node", id: "n1", parameters: { spreadsheet_id: "{{ $json.sheet }}" }, ...{} }]);
  });

  it("keeps a saved id that is not in the list and filters by the search box", async () => {
    panel(node({ parameters: { spreadsheet_id: "1GoneAbCdEfGhIjKlMnOpQrStUv99" } }));
    const select = await screen.findByRole("combobox", { name: /spreadsheet id/i });
    await waitFor(() => expect(within(select).getByText(/Test Leads/)).toBeInTheDocument());
    expect(within(select).getByText(/1GoneAbCdEfGhIjKlMnOpQrStUv99/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Search spreadsheet id/i), "sales");
    expect(within(select).queryByText(/Test Leads/)).not.toBeInTheDocument();
    expect(within(select).getByText(/Sales 2026/)).toBeInTheDocument();
  });
});

describe("dependent fields", () => {
  it("the tab list waits for a spreadsheet, then loads its tabs", async () => {
    const { rerender } = panel(node());
    expect((await screen.findAllByText(/Choose “spreadsheet id” first/)).length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Tab")).toBeDisabled();
    expect(callsFor("range")).toHaveLength(0);

    rerender(
      <ConfigPanel workflowId="w" workflow={workflow} node={node({ parameters: { spreadsheet_id: FILES[0].value } })} nodeType={APPEND}
        siblings={SIBLINGS} published={false} lastRun={undefined} triggers={[]} onApply={onApply as never} onDeleteNode={vi.fn()} onTested={vi.fn()} />,
    );
    await waitFor(() => expect(callsFor("range")).toHaveLength(1));
    expect(callsFor("range")[0][1]).toMatchObject({ parameters: { spreadsheet_id: FILES[0].value } });
    await waitFor(() => expect(screen.getByLabelText("Tab")).toBeEnabled());
  });

  it("choosing a tab saves the range and clears the column values", async () => {
    panel(node({ parameters: { spreadsheet_id: FILES[0].value, range: "Sheet1!A:B", values: ["x", "y"] } }));
    const tab = await screen.findByLabelText("Tab");
    await waitFor(() => expect(within(tab).getByText("Q4 data")).toBeInTheDocument());
    await userEvent.selectOptions(tab, "Q4 data");
    expect(onApply).toHaveBeenLastCalledWith([{
      op: "update_node", id: "n1", parameters: { range: "'Q4 data'!A:B" }, remove_parameters: ["values"],
    }]);
  });

  it("changing the account clears every loaded value", async () => {
    panel(node({ parameters: { spreadsheet_id: FILES[0].value, range: "Sheet1", values: ["a"] } }));
    await userEvent.selectOptions(await screen.findByLabelText(/Account/), "c2");
    expect(onApply).toHaveBeenLastCalledWith([{
      op: "update_node", id: "n1", connection_id: "c2", remove_parameters: ["spreadsheet_id", "range", "values"],
    }]);
  });

  it("dependentsOf follows the chain", () => {
    const props = { spreadsheet_id: str(SS), range: str(TAB), values: { type: "array", "x-ui": COLS } as JsonSchema, title: str() };
    expect(dependentsOf(props, "spreadsheet_id")).toEqual(["range", "values"]);
    expect(dependentsOf(props, "range")).toEqual(["values"]);
    expect(dependentsOf(props, "title")).toEqual([]);
  });
});

describe("loading, empty and error states", () => {
  it("shows loading, then the empty state", async () => {
    let resolve!: (v: { options: Option[]; cached: boolean; loader: string }) => void;
    load.mockImplementationOnce(() => new Promise((r) => { resolve = r; }));
    panel(node());
    expect(await screen.findByRole("status")).toHaveTextContent(/Loading/);
    resolve({ options: [], cached: false, loader: "spreadsheets" });
    expect(await screen.findByText(/Nothing found in this account/)).toBeInTheDocument();
  });

  it("missing scopes show the message and a Reconnect button", async () => {
    load.mockRejectedValueOnce(new ApiError(409, "Google Sheets is connected, but Google did not grant the Drive permission. Reconnect Google Sheets.", { code: "reconnect" }));
    panel(node());
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/Reconnect Google Sheets/);
    expect(within(alert).getByRole("link", { name: "Reconnect" })).toHaveAttribute("href", "/connections");
  });

  it("other errors offer Try again, which reloads", async () => {
    load.mockRejectedValueOnce(new ApiError(502, "Google is having trouble. Next step: retry in a minute.", { code: "server" }));
    panel(node());
    await userEvent.click(await screen.findByRole("button", { name: "Try again" }));
    await waitFor(() => expect(callsFor("spreadsheet_id").length).toBeGreaterThanOrEqual(2));
    expect(callsFor("spreadsheet_id").at(-1)![1]).toMatchObject({ refresh: true });
  });

  it("asks for an account first when none is chosen", async () => {
    panel(node({ connection_id: undefined }));
    expect(await screen.findAllByText("Choose an account first.")).not.toHaveLength(0);
    expect(load).not.toHaveBeenCalled();
  });

  it("the refresh icon reloads past the cache", async () => {
    panel(node());
    await waitFor(() => expect(callsFor("spreadsheet_id")).toHaveLength(1));
    await userEvent.click(screen.getByRole("button", { name: /Refresh spreadsheet id/i }));
    await waitFor(() => expect(callsFor("spreadsheet_id")).toHaveLength(2));
    expect(callsFor("spreadsheet_id")[1][1]).toMatchObject({ refresh: true });
  });
});

describe("key-value column mapper", () => {
  const withSheet = { spreadsheet_id: FILES[0].value, range: "Sheet1!A:B" };

  it("shows one input per header and saves the row in header order", async () => {
    panel(node({ parameters: withSheet }));
    const email = await screen.findByLabelText("Email");
    await userEvent.type(email, "a@x.com");
    await userEvent.tab();
    expect(onApply).toHaveBeenLastCalledWith([{ op: "update_node", id: "n1", parameters: { values: ["", "a@x.com"] } }]);
  });

  it("auto-maps every column from the input item", async () => {
    panel(node({ parameters: withSheet }));
    await screen.findByLabelText("Name");
    await userEvent.click(screen.getByRole("button", { name: "Auto-map from input" }));
    expect(onApply).toHaveBeenLastCalledWith([{
      op: "update_node", id: "n1", parameters: { values: ['{{ $json["Name"] }}', '{{ $json["Email"] }}'] },
    }]);
  });

  it("shows saved values and builds objects / JSON for apps that take field names", () => {
    const opts: Option[] = [{ value: "Name", name: "Name" }, { value: "Email", name: "Email" }];
    expect(buildMapped(["Ada", ""], opts, "object")).toEqual({ Name: "Ada" });
    expect(buildMapped(["Ada", "a@x.com"], opts, "json")).toBe('{"Name":"Ada","Email":"a@x.com"}');
    expect(buildMapped(["", ""], opts, "json")).toBeNull();
    expect(buildMapped(["x", "y"], opts, "array")).toEqual(["x", "y"]);
  });

  it("waits for the tab before listing columns", async () => {
    panel(node({ parameters: { spreadsheet_id: FILES[0].value } }));
    expect(await screen.findByText(/Choose “range” first/)).toBeInTheDocument();
    expect(callsFor("values")).toHaveLength(0);
  });
});

describe("dropdown and multi-select kinds", () => {
  const SLACK = { ...nt("slack__post_message", "Message", "Post", {
    channel: str({ kind: "options", loader: "channels" }),
    teams: { type: "array", "x-ui": { kind: "multi", loader: "calendars" } } as JsonSchema,
  }), connector: "slack" } as NodeType;

  it("a plain dropdown loads from the account and can switch to an expression", async () => {
    load.mockResolvedValue({ options: [{ value: "C1", name: "#general", description: "bot is a member" }], cached: false, loader: "channels" });
    vi.spyOn(workflowsApi, "connections").mockResolvedValue([{ id: "c1", provider: "slack", account_label: "T", status: "active" }]);
    panel(node({ type: SLACK.type, parameters: {} }), SLACK);
    const select = await screen.findByRole("combobox", { name: /channel/i });
    await waitFor(() => expect(within(select).getByText(/#general/)).toBeInTheDocument());
    await userEvent.selectOptions(select, "C1");
    expect(onApply).toHaveBeenLastCalledWith([{ op: "update_node", id: "n1", parameters: { channel: "C1" } }]);
    await userEvent.click(screen.getAllByRole("button", { name: "Expression" })[0]);
    expect(screen.getByPlaceholderText("{{ $json.value }}")).toBeInTheDocument();
  });

  it("a multi-select saves the chosen values as a list", async () => {
    load.mockResolvedValue({ options: [{ value: "a", name: "Cal A" }, { value: "b", name: "Cal B" }], cached: false, loader: "calendars" });
    vi.spyOn(workflowsApi, "connections").mockResolvedValue([{ id: "c1", provider: "slack", account_label: "T", status: "active" }]);
    panel(node({ type: SLACK.type, parameters: { teams: ["a"] } }), SLACK);
    await userEvent.click(await screen.findByLabelText("Cal B"));
    expect(onApply).toHaveBeenLastCalledWith([{ op: "update_node", id: "n1", parameters: { teams: ["a", "b"] } }]);
    onApply.mockClear();
    await userEvent.click(screen.getByLabelText("Cal A"));
    expect(onApply).toHaveBeenLastCalledWith([{ op: "update_node", id: "n1", parameters: { teams: null } }]);
  });
});

describe("helpers", () => {
  it("idFromUrl uses the connector's pattern", () => {
    expect(idFromUrl("https://docs.google.com/spreadsheets/d/1LeadsAbCdEfGhIjKlMnOpQrStUv01/edit", URL_PATTERN)).toBe("1LeadsAbCdEfGhIjKlMnOpQrStUv01");
    expect(idFromUrl("nope", URL_PATTERN)).toBeNull();
    expect(idFromUrl("  abc ", undefined)).toBe("abc");
    expect(idFromUrl("", URL_PATTERN)).toBeNull();
    expect(idFromUrl("https://github.com/o/api/issues/3", "github\\.com/([^/\\s]+/[^/\\s#?]+)")).toBe("o/api");
  });

  it("splitRange and joinRange round-trip tab names with spaces and quotes", () => {
    expect(splitRange("'Q4 data'!A:B")).toEqual({ tab: "Q4 data", cells: "A:B" });
    expect(splitRange("Sheet1")).toEqual({ tab: "Sheet1", cells: "" });
    expect(joinRange("Q4 data", "A:B")).toBe("'Q4 data'!A:B");
    expect(joinRange("Sheet1", "A:Z")).toBe("Sheet1!A:Z");
    expect(joinRange("It's", "")).toBe("'It''s'");
    expect(splitRange(joinRange("It's", "A1"))).toEqual({ tab: "It's", cells: "A1" });
  });
});

describe("optionsApi cache", () => {
  const req = { parameter: "spreadsheet_id", connection_id: "c1", parameters: {} };

  beforeEach(() => {
    load.mockRestore();
    vi.mocked(apiFetch).mockReset().mockResolvedValue({ options: FILES, cached: false, loader: "spreadsheets" });
  });

  it("caches for a minute, per account, inputs and query; refresh bypasses it", async () => {
    await optionsApi.load("t", req);
    expect((await optionsApi.load("t", req)).cached).toBe(true);
    expect(apiFetch).toHaveBeenCalledTimes(1);
    await optionsApi.load("t", { ...req, connection_id: "c2" });
    await optionsApi.load("t", { ...req, query: "x" });
    await optionsApi.load("t", { ...req, parameters: { a: 1 } });
    expect(apiFetch).toHaveBeenCalledTimes(4);
    await optionsApi.load("t", { ...req, refresh: true });
    expect(apiFetch).toHaveBeenCalledTimes(5);
  });

  it("expires after the TTL and never caches failures", async () => {
    const now = vi.spyOn(Date, "now");
    now.mockReturnValue(1_000);
    await optionsApi.load("t", req);
    now.mockReturnValue(1_000 + OPTIONS_TTL_MS + 1);
    await optionsApi.load("t", req);
    expect(apiFetch).toHaveBeenCalledTimes(2);
    vi.mocked(apiFetch).mockRejectedValueOnce(new ApiError(502, "x"));
    await expect(optionsApi.load("t", { ...req, query: "boom" })).rejects.toBeInstanceOf(ApiError);
    await optionsApi.load("t", { ...req, query: "boom" });
    expect(apiFetch).toHaveBeenCalledTimes(4);
  });

  it("posts to /api/nodes/{type}/options", async () => {
    await optionsApi.load("google_sheets__append_row", req);
    expect(apiFetch).toHaveBeenCalledWith("/api/nodes/google_sheets__append_row/options", expect.objectContaining({ method: "POST" }));
  });
});
