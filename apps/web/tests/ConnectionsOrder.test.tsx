import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }), useSearchParams: () => new URLSearchParams() }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: vi.fn() }));

import { ConnectionsView } from "@/components/ConnectionsView";
import { ToastProvider } from "@/components/ui/Toast";
import { connectionsApi, type Connector } from "@/lib/connections";

const c = (id: string, name: string, configured: boolean): Connector => ({
  id, name, icon: "", description: "d", auth_type: "oauth2", app_provider: id, configured, setup: {} as never,
  credential_fields: [], redirect_uri: "", redirect_info: {} as never, scopes: [], console_url: null, setup_guide: [], setup_url: null, tools: [],
});

afterEach(() => vi.restoreAllMocks());

describe("Connections grid", () => {
  it("lists Connected apps first, then ready, then not set up", async () => {
    vi.spyOn(connectionsApi, "connectors").mockResolvedValue([c("trello", "Trello", false), c("notion", "Notion", true), c("github", "GitHub", true)]);
    vi.spyOn(connectionsApi, "list").mockResolvedValue([
      { id: "x", provider: "github", status: "active", account_label: "o", scopes: [], expires_at: null, auto_approve_writes: false, created_at: "", provider_app_id: "a" },
    ] as never);
    render(<ToastProvider><ConnectionsView /></ToastProvider>);
    await screen.findByRole("heading", { name: "GitHub" });
    const names = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(names).toEqual(["GitHub", "Notion", "Trello"]);
  });
});
