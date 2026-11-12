import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: vi.fn() }));

import { ConnectionCard } from "@/components/ConnectionCard";
import { ConnectModal } from "@/components/connections/ConnectModal";
import { ApiError } from "@/lib/api";
import { categoryOf, providerAppsApi, type Connection, type Connector, type SetupInfo } from "@/lib/connections";

const noSetup: SetupInfo = {
  provider: "github", source: "none", client_id_masked: null, fields: {}, secrets_set: [],
  platform_available: false, created_at: null, redirect_uri_changed: false, registered_redirect_uri: null,
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
  redirect_uri: "http://localhost:8000/api/oauth/callback/github",
  redirect_info: { mode: "localhost", localhost_redirect: "unverified", note: "GitHub docs do not state a localhost rule." },
  scopes: [], console_url: "https://github.com/settings/apps",
  setup_guide: ["Create a GitHub App"], setup_url: null,
  tools: [{ name: "github__create_issue", risk: "write" }],
};
const ready: Connector = { ...base, configured: true, setup: userSetup };

const conn = (over: Partial<Connection> = {}): Connection => ({
  id: "c1", provider: "github", status: "active", account_label: "octocat", scopes: [],
  expires_at: null, auto_approve_writes: false, created_at: "2026-11-11T00:00:00Z", provider_app_id: "app1", ...over,
});

const handlers = () => ({
  onClose: vi.fn(), onConnect: vi.fn(), onDisconnect: vi.fn(), onToggleAutoApprove: vi.fn(), onSetupChanged: vi.fn(), onTest: vi.fn(),
});

function card(connector: Connector, connections: Connection[] = []) {
  const onOpen = vi.fn();
  render(<ConnectionCard connector={connector} connections={connections} onOpen={onOpen} />);
  return onOpen;
}

function modal(connector: Connector, connections: Connection[] = [], extra: Partial<ReturnType<typeof handlers>> = {}) {
  const h = { ...handlers(), ...extra };
  render(<ConnectModal connector={connector} connections={connections} busy={false} {...h} />);
  return h;
}

const step = (name: RegExp) => userEvent.click(screen.getByRole("button", { name }));

afterEach(() => vi.restoreAllMocks());

describe("integration cards", () => {
  it("Not set up: the button is Set up and opens the dialog", async () => {
    const onOpen = card(base);
    expect(screen.getByText("Not set up")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "GitHub" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Set up GitHub" }));
    expect(onOpen).toHaveBeenCalledWith(base);
  });

  it("Ready to connect: Connect", () => {
    card(ready);
    expect(screen.getByText("Ready to connect")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect GitHub" })).toBeInTheDocument();
  });

  it("Connected: status, account count, Manage", () => {
    card(ready, [conn()]);
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByText(/1 account · octocat/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Manage GitHub" })).toBeInTheDocument();
  });

  it("Partial access and Needs reconnect offer Reconnect", () => {
    card(ready, [conn({ partial: true, missing_scopes: ["x"] })]);
    expect(screen.getByText("Partial access")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconnect GitHub" })).toBeInTheDocument();
  });

  it("Needs reconnect", () => {
    card(ready, [conn({ status: "needs_reauth" })]);
    expect(screen.getByText("Needs reconnect")).toBeInTheDocument();
  });

  it("shows the brand logo (or a monogram when the brand is not in Simple Icons)", () => {
    card(ready);
    expect(screen.getByRole("img", { name: "GitHub logo" })).toBeInTheDocument();
    card({ ...ready, id: "slack", name: "Slack" });
    expect(screen.getByTestId("brand-fallback")).toHaveTextContent("S");
  });

  it("groups connectors into categories", () => {
    expect(categoryOf("google_sheets")).toBe("Google Workspace");
    expect(categoryOf("gmail")).toBe("Google Workspace");
    expect(categoryOf("slack")).toBe("Communication");
    expect(categoryOf("github")).toBe("Developer");
  });
});

describe("dialog flow", () => {
  it("opens on the step that fits the state", () => {
    modal(base);
    expect(screen.getByRole("heading", { name: /1\. Create credentials/ })).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toHaveAccessibleName("GitHub");
  });

  it("Ready to connect opens on Authorize, and Connect starts the connection", async () => {
    const h = modal(ready);
    expect(screen.getByRole("heading", { name: /3\. Authorize/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(h.onConnect).toHaveBeenCalledWith(ready);
  });

  it("Connected: account, auto-approve toggle, confirm before disconnect, add another account", async () => {
    const h = modal(ready, [conn()]);
    await userEvent.click(screen.getByLabelText("Auto-approve writes"));
    expect(h.onToggleAutoApprove).toHaveBeenCalledWith(expect.objectContaining({ id: "c1" }), true);
    await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    expect(h.onDisconnect).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Confirm disconnect" }));
    expect(h.onDisconnect).toHaveBeenCalledWith(expect.objectContaining({ id: "c1" }));
    await userEvent.click(screen.getByRole("button", { name: "Add another account" }));
    expect(h.onConnect).toHaveBeenCalledWith(ready);
  });

  it("Partial access: lists what was not granted and every granted permission (always visible), with Reconnect", async () => {
    const SHEETS = "https://www.googleapis.com/auth/spreadsheets";
    const h = modal({ ...ready, id: "google_sheets", name: "Google Sheets" }, [conn({
      provider: "google_sheets", partial: true, missing_scopes: [SHEETS],
      scopes: ["openid", "https://www.googleapis.com/auth/userinfo.email"],
    })]);
    expect(screen.getByRole("alert")).toHaveTextContent(/did not grant: Google Sheets \(read and write\)/);
    expect(screen.getByRole("alert")).toHaveTextContent("Reconnect Google Sheets and tick the Sheets permission");
    expect(screen.getByText(/Granted permissions \(2\)/)).toBeInTheDocument();
    expect(screen.getByText("Email address")).toBeInTheDocument();
    expect(screen.getByText("Sign-in (openid)")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reconnect" }));
    expect(h.onConnect).toHaveBeenCalled();
  });

  it("Connected with every permission shows no warning", () => {
    modal(ready, [conn({ partial: false, missing_scopes: [], scopes: ["openid"] })]);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("Step 1 and 2: credentials", () => {
  it("shows the guide, console link, exactly one redirect URI with a Copy button and the provider note", async () => {
    modal(base);
    expect(screen.getByText("Create a GitHub App")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /developer console/ })).toHaveAttribute("href", "https://github.com/settings/apps");
    expect(screen.getAllByText(/\/api\/oauth\/callback\//)).toHaveLength(1);
    expect(screen.getByText("http://localhost:8000/api/oauth/callback/github")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy" })).toBeInTheDocument();
    expect(screen.getByText("localhost (works for Google and GitHub in dev)")).toBeInTheDocument();
    expect(screen.getByText(/do not state a localhost rule/)).toBeInTheDocument();
  });

  it("renders manifest fields and saves values; the secret is cleared afterwards", async () => {
    const save = vi.spyOn(providerAppsApi, "save").mockResolvedValue(userSetup);
    const h = modal(base);
    await step(/Enter credentials/);
    const secret = screen.getByLabelText("Client secret");
    expect(secret).toHaveAttribute("type", "password");
    await userEvent.type(screen.getByLabelText("Client ID"), "Iv23abc");
    await userEvent.type(secret, "s3cret");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(save).toHaveBeenCalledWith("github", { client_id: "Iv23abc", client_secret: "s3cret", app_slug: "" });
    expect(h.onSetupChanged).toHaveBeenCalled();
    expect(secret).toHaveValue("");
  });

  it("tunnel mode shows the HTTPS URI and the tunnel status line", () => {
    const uri = "https://quiet-words.trycloudflare.com/api/oauth/callback/slack";
    modal({ ...base, id: "slack", name: "Slack", redirect_uri: uri,
      redirect_info: { mode: "tunnel", localhost_redirect: "no", note: null } });
    expect(screen.getByText(uri)).toBeInTheDocument();
    expect(screen.getByText("public HTTPS tunnel")).toBeInTheDocument();
    expect(screen.queryByText(/will not accept this localhost URI/)).not.toBeInTheDocument();
  });

  it("warns when a provider that needs HTTPS is still on localhost", () => {
    modal({ ...base, id: "slack", name: "Slack", redirect_info: { mode: "localhost", localhost_redirect: "no", note: null } });
    expect(screen.getByText(/Slack will not accept this localhost URI/)).toBeInTheDocument();
  });

  it("shows a banner when the redirect URI changed, and clears it on acknowledge", async () => {
    const ack = vi.spyOn(providerAppsApi, "ackRedirectUri").mockResolvedValue(userSetup);
    const changed: Connector = { ...ready, setup: { ...userSetup, redirect_uri_changed: true,
      registered_redirect_uri: "http://localhost:8000/api/oauth/callback/github" } };
    const h = modal(changed, [], {});
    await step(/Create credentials/);
    expect(screen.getByText(/redirect URI changed since you saved/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /updated it/ }));
    expect(ack).toHaveBeenCalledWith("github");
    expect(h.onSetupChanged).toHaveBeenCalled();
  });

  it("no banner when the redirect URI is unchanged", async () => {
    modal(ready);
    await step(/Create credentials/);
    expect(screen.queryByText(/redirect URI changed/)).not.toBeInTheDocument();
  });

  it("shows field errors from the API", async () => {
    vi.spyOn(providerAppsApi, "save").mockRejectedValue(
      new ApiError(422, "Please fix the highlighted fields.", { errors: { client_id: "GitHub App client IDs start with Iv" } }),
    );
    modal(base);
    await step(/Enter credentials/);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByLabelText("Client ID")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(/start with Iv/)).toBeInTheDocument();
  });

  it("saved secrets show as kept, and Test reports the result", async () => {
    vi.spyOn(providerAppsApi, "test").mockResolvedValue({ ok: false, source: "user", message: "The provider rejected the client ID or secret.", errors: {} });
    modal(ready);
    await step(/Enter credentials/);
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
    const h = modal(ready, [conn()]);
    await step(/Enter credentials/);
    await userEvent.click(screen.getByRole("button", { name: "Remove credentials" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    const warning = await screen.findByText(/will disconnect 1 connection: octocat/);
    await userEvent.click(within(warning.parentElement!).getByRole("button", { name: "Remove and disconnect" }));
    expect(remove).toHaveBeenNthCalledWith(1, "github", false);
    expect(remove).toHaveBeenNthCalledWith(2, "github", true);
    expect(h.onSetupChanged).toHaveBeenCalled();
  });

  it("the platform default app is explained in step 2", async () => {
    modal({ ...base, configured: true, setup: { ...noSetup, source: "platform", platform_available: true } });
    await step(/Enter credentials/);
    expect(screen.getAllByText(/default app/).length).toBeGreaterThan(0);
  });
});

describe("Step 4: test connection", () => {
  it("shows Not tested yet and a Test connection button that calls onTest", async () => {
    const h = modal(ready, [conn()]);
    expect(screen.getByText("Not tested yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /test connection octocat/i }));
    expect(h.onTest).toHaveBeenCalledWith(expect.objectContaining({ id: "c1" }));
  });

  it("shows pass/fail with the provider message and time", () => {
    modal(ready, [conn({
      last_checked_at: new Date().toISOString(), last_check_ok: false,
      last_check_message: "GitHub failed (401): the provider rejected the credentials.",
    })]);
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText(/checked just now/i)).toBeInTheDocument();
    expect(screen.getByText(/rejected the credentials/i)).toBeInTheDocument();
  });
});
