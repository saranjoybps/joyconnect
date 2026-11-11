import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: vi.fn() }));

import { ConnectionCard } from "@/components/ConnectionCard";
import { ApiError } from "@/lib/api";
import { providerAppsApi, type Connection, type Connector, type SetupInfo } from "@/lib/connections";

const noSetup: SetupInfo = {
  provider: "github", source: "none", client_id_masked: null, fields: {}, secrets_set: [],
  platform_available: false, created_at: null,
};
const userSetup: SetupInfo = {
  ...noSetup, source: "user", client_id_masked: "Iv23…3456", fields: { app_slug: "my-app" },
  secrets_set: ["client_secret"], created_at: "2026-11-11T00:00:00Z",
};

const base: Connector = {
  id: "github", name: "GitHub", icon: "/icons/github.svg", description: "Issues", auth_type: "oauth2",
  app_provider: "github", configured: false, setup: noSetup,
  credential_fields: [
    { key: "client_id", label: "Client ID", secret: false, help_text: "From the app page", required: true, pattern_hint: "" },
    { key: "client_secret", label: "Client secret", secret: true, help_text: "Generate one", required: true, pattern_hint: "" },
    { key: "app_slug", label: "App slug", secret: false, help_text: "", required: false, pattern_hint: "" },
  ],
  redirect_uris: ["http://localhost:8000/api/oauth/callback/github"],
  scopes: [], console_url: "https://github.com/settings/apps",
  setup_guide: ["Create a GitHub App"], setup_url: null,
  tools: [{ name: "github__create_issue", risk: "write" }],
};
const ready: Connector = { ...base, configured: true, setup: userSetup };

const conn = (over: Partial<Connection> = {}): Connection => ({
  id: "c1", provider: "github", status: "active", account_label: "octocat", scopes: [],
  expires_at: null, auto_approve_writes: false, created_at: "2026-11-11T00:00:00Z", provider_app_id: "app1", ...over,
});

function setup(connector: Connector, connections: Connection[] = []) {
  const handlers = { onConnect: vi.fn(), onDisconnect: vi.fn(), onToggleAutoApprove: vi.fn(), onSetupChanged: vi.fn() };
  render(<ConnectionCard connector={connector} connections={connections} busy={false} {...handlers} />);
  return handlers;
}

afterEach(() => vi.restoreAllMocks());

describe("ConnectionCard states", () => {
  it("Not set up: only Set up is offered", () => {
    setup(base);
    expect(screen.getByText("Not set up")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set up" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect" })).not.toBeInTheDocument();
  });

  it("Ready to connect: Connect and Edit setup, masked client id", async () => {
    const h = setup(ready);
    expect(screen.getByText("Ready to connect")).toBeInTheDocument();
    expect(screen.getByText("Iv23…3456")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(h.onConnect).toHaveBeenCalledWith(ready);
    expect(screen.getByRole("button", { name: "Edit setup" })).toBeInTheDocument();
  });

  it("Connected: account, auto-approve toggle, confirm before disconnect", async () => {
    const h = setup(ready, [conn()]);
    expect(screen.getByText("Connected")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Auto-approve writes"));
    expect(h.onToggleAutoApprove).toHaveBeenCalledWith(expect.objectContaining({ id: "c1" }), true);
    await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    expect(h.onDisconnect).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Confirm disconnect" }));
    expect(h.onDisconnect).toHaveBeenCalledWith(expect.objectContaining({ id: "c1" }));
  });

  it("Needs reconnect", () => {
    setup(ready, [conn({ status: "needs_reauth" })]);
    expect(screen.getByText("Needs reconnect")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconnect" })).toBeInTheDocument();
  });

  it("Platform default app offers 'Use my own app'", () => {
    setup({ ...base, configured: true, setup: { ...noSetup, source: "platform", platform_available: true } });
    expect(screen.getByText("Ready to connect")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use my own app" })).toBeInTheDocument();
  });
});

describe("Set up panel", () => {
  it("renders manifest fields, redirect URI and guide, and saves values", async () => {
    const save = vi.spyOn(providerAppsApi, "save").mockResolvedValue(userSetup);
    const h = setup(base);
    await userEvent.click(screen.getByRole("button", { name: "Set up" }));
    expect(screen.getByText("http://localhost:8000/api/oauth/callback/github")).toBeInTheDocument();
    expect(screen.getByText("Create a GitHub App")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /developer console/ })).toHaveAttribute("href", "https://github.com/settings/apps");
    const secret = screen.getByLabelText("Client secret");
    expect(secret).toHaveAttribute("type", "password");
    await userEvent.type(screen.getByLabelText("Client ID"), "Iv23abc");
    await userEvent.type(secret, "s3cret");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(save).toHaveBeenCalledWith("github", { client_id: "Iv23abc", client_secret: "s3cret", app_slug: "" });
    expect(h.onSetupChanged).toHaveBeenCalled();
    expect(secret).toHaveValue(""); // secret cleared from the form after saving
  });

  it("shows field errors from the API", async () => {
    vi.spyOn(providerAppsApi, "save").mockRejectedValue(
      new ApiError(422, "Please fix the highlighted fields.", { errors: { client_id: "GitHub App client IDs start with Iv" } }),
    );
    setup(base);
    await userEvent.click(screen.getByRole("button", { name: "Set up" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByLabelText("Client ID")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(/start with Iv/)).toBeInTheDocument();
  });

  it("saved secrets show as kept, and Test reports the result", async () => {
    vi.spyOn(providerAppsApi, "test").mockResolvedValue({ ok: false, source: "user", message: "The provider rejected the client ID or secret.", errors: {} });
    setup(ready);
    await userEvent.click(screen.getByRole("button", { name: "Edit setup" }));
    expect(screen.getByLabelText("Client secret")).toHaveAttribute("placeholder", "Saved. Leave blank to keep");
    await userEvent.click(screen.getByRole("button", { name: "Test" }));
    expect(await screen.findByText(/rejected the client ID/)).toBeInTheDocument();
  });

  it("warns before removing credentials that have connections", async () => {
    const remove = vi.spyOn(providerAppsApi, "remove")
      .mockRejectedValueOnce(new ApiError(409, "Removing...", {
        code: "has_connections", connections: [{ id: "c1", provider: "github", account_label: "octocat" }],
      }))
      .mockResolvedValueOnce({ ok: true, disconnected: 1 });
    const h = setup(ready, [conn()]);
    await userEvent.click(screen.getByRole("button", { name: "Edit setup" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove credentials" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    const warning = await screen.findByText(/will disconnect 1 connection: octocat/);
    await userEvent.click(within(warning.parentElement!).getByRole("button", { name: "Remove and disconnect" }));
    expect(remove).toHaveBeenNthCalledWith(1, "github", false);
    expect(remove).toHaveBeenNthCalledWith(2, "github", true);
    expect(h.onSetupChanged).toHaveBeenCalled();
  });
});
