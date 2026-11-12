import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: vi.fn() }));

import { RunsView } from "@/components/RunsView";
import { formatDuration, runsApi, type Run, type RunsPage } from "@/lib/runs";

const run = (over: Partial<Run> = {}): Run => ({
  id: "r1", created_at: "2026-11-12T10:00:00Z", finished_at: "2026-11-12T10:00:01Z", connector: "stripe",
  connector_name: "Stripe", tool: "stripe__get_balance", action: "Get balance", risk: "read", status: "ok",
  duration_ms: 420, conversation_id: "c1", input: { api_key: "[REDACTED]" }, output: { available: [] }, ...over,
});
const page = (runs: Run[]): RunsPage => ({
  runs, total: runs.length, statuses: ["pending", "approved", "rejected", "ok", "error"],
  connectors: [{ id: "stripe", name: "Stripe" }, { id: "slack", name: "Slack" }],
});

afterEach(() => vi.restoreAllMocks());

describe("RunsView", () => {
  it("lists runs with connector, tool, risk, status, duration and redacted input/output", async () => {
    vi.spyOn(runsApi, "list").mockResolvedValue(page([run(), run({ id: "r2", status: "error", risk: "write",
      connector: "slack", connector_name: "Slack", action: "Post message", duration_ms: 1500,
      output: { error: "Slack needs reconnecting" } })]));
    render(<RunsView />);
    expect(await screen.findByText("Get balance")).toBeInTheDocument();
    expect(screen.getByText("Post message")).toBeInTheDocument();
    expect(screen.getByText("420 ms")).toBeInTheDocument();
    expect(screen.getByText("1.5 s")).toBeInTheDocument();
    expect(screen.getAllByText("error").some((el) => el.tagName === "SPAN")).toBe(true);   // status badge (the option is also "error")
    expect(screen.getAllByText(/\[REDACTED\]/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Slack needs reconnecting/)).toBeInTheDocument();
  });

  it("re-queries with the chosen connector and status filters", async () => {
    const spy = vi.spyOn(runsApi, "list").mockResolvedValue(page([run()]));
    render(<RunsView />);
    await screen.findByText("Get balance");
    await userEvent.selectOptions(screen.getByLabelText("Connector"), "slack");
    await waitFor(() => expect(spy).toHaveBeenLastCalledWith(expect.objectContaining({ connector: "slack", offset: 0 })));
    await userEvent.selectOptions(screen.getByLabelText("Status"), "error");
    await waitFor(() => expect(spy).toHaveBeenLastCalledWith(expect.objectContaining({ connector: "slack", status: "error" })));
  });

  it("shows an empty state and API errors", async () => {
    vi.spyOn(runsApi, "list").mockResolvedValueOnce(page([]));
    const { unmount } = render(<RunsView />);
    expect(await screen.findByText(/No runs match/)).toBeInTheDocument();
    unmount();
    vi.spyOn(runsApi, "list").mockRejectedValueOnce(new Error("Unauthorized"));
    render(<RunsView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Unauthorized");
  });

  it("formats durations", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(999)).toBe("999 ms");
    expect(formatDuration(2500)).toBe("2.5 s");
  });
});
