import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }), usePathname: () => "/workflows" }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: vi.fn() }));

import { WorkflowsView } from "@/components/WorkflowsView";
import { workflowsApi, type WorkflowSummary } from "@/lib/workflows";

const wf = (over: Partial<WorkflowSummary> = {}): WorkflowSummary => ({
  id: "w1", name: "Daily report", status: "draft", version: 3, published_version: null, updated_at: null, node_count: 2, ...over,
});

afterEach(() => {
  vi.restoreAllMocks();
  push.mockClear();
});

describe("WorkflowsView", () => {
  it("lists workflows with status, node count and version", async () => {
    vi.spyOn(workflowsApi, "list").mockResolvedValue([wf(), wf({ id: "w2", name: "Hook", status: "published", node_count: 1 })]);
    render(<WorkflowsView />);
    expect(await screen.findByText("Daily report")).toBeInTheDocument();
    expect(screen.getByText("Published")).toBeInTheDocument();
    expect(screen.getByText("2 nodes")).toBeInTheDocument();
    expect(screen.getByText("1 node")).toBeInTheDocument();
  });

  it("creates a workflow and opens it on the canvas", async () => {
    vi.spyOn(workflowsApi, "list").mockResolvedValue([]);
    const create = vi.spyOn(workflowsApi, "create").mockResolvedValue({ workflow: { id: "new1" } as never });
    render(<WorkflowsView />);
    await screen.findByText(/No workflows yet/);
    await userEvent.type(screen.getByLabelText("Workflow name"), "Invoices");
    await userEvent.click(screen.getByRole("button", { name: "New workflow" }));
    expect(create).toHaveBeenCalledWith("Invoices");
    await waitFor(() => expect(push).toHaveBeenCalledWith("/workflows/new1"));
  });

  it("asks for confirmation before deleting, and cancel deletes nothing", async () => {
    vi.spyOn(workflowsApi, "list").mockResolvedValue([wf()]);
    const remove = vi.spyOn(workflowsApi, "remove").mockResolvedValue({ ok: true });
    render(<WorkflowsView />);
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Delete “Daily report”?");
    expect(remove).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(remove).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete workflow" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("w1"));
  });
});
