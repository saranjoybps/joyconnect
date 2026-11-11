import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConnectionCard } from "@/components/ConnectionCard";
import type { Connection, Connector } from "@/lib/connections";

const connector: Connector = {
  id: "slack", name: "Slack", icon: "/icons/slack.svg", description: "Post messages",
  auth_type: "oauth2", configured: true, setup_url: null,
  tools: [{ name: "slack__post_message", risk: "write" }],
};

const conn = (over: Partial<Connection> = {}): Connection => ({
  id: "c1", provider: "slack", status: "active", account_label: "Acme", scopes: [],
  expires_at: null, auto_approve_writes: false, created_at: "2026-11-11T00:00:00Z", ...over,
});

function setup(connections: Connection[], c: Connector = connector) {
  const handlers = { onConnect: vi.fn(), onDisconnect: vi.fn(), onToggleAutoApprove: vi.fn() };
  render(<ConnectionCard connector={c} connections={connections} busy={false} {...handlers} />);
  return handlers;
}

describe("ConnectionCard", () => {
  it("shows Connect when not connected", async () => {
    const h = setup([]);
    expect(screen.getByText("Not connected")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(h.onConnect).toHaveBeenCalledWith(connector);
    expect(screen.queryByLabelText("Auto-approve writes")).not.toBeInTheDocument();
  });

  it("shows Connected with account and auto-approve toggle", async () => {
    const h = setup([conn()]);
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("Acme")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Auto-approve writes"));
    expect(h.onToggleAutoApprove).toHaveBeenCalledWith(expect.objectContaining({ id: "c1" }), true);
  });

  it("shows Reconnect when a connection needs reauth", () => {
    setup([conn({ status: "needs_reauth" })]);
    expect(screen.getByText("Needs reconnect")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconnect" })).toBeInTheDocument();
  });

  it("asks for confirmation before disconnecting", async () => {
    const h = setup([conn()]);
    await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    expect(h.onDisconnect).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Confirm disconnect" }));
    expect(h.onDisconnect).toHaveBeenCalledWith(expect.objectContaining({ id: "c1" }));
  });

  it("hides Connect for connectors not configured on the server", () => {
    setup([], { ...connector, configured: false });
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect" })).not.toBeInTheDocument();
  });
});
