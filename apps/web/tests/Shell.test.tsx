import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn() }), usePathname: () => "/runs" }));
vi.mock("next/link", () => ({ default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a> }));
vi.mock("@/lib/supabase/client", () => ({
  getSupabaseBrowserClient: () => ({
    auth: { getSession: async () => ({ data: { session: { user: { id: "u1", email: "ada.lovelace@x.com", user_metadata: {} } } } }), signOut: vi.fn() },
  }),
}));

import { HistoryPanel } from "@/components/shell/HistoryPanel";
import { Sidebar } from "@/components/shell/Sidebar";
import { ThemeProvider } from "@/components/ui/theme";
import { ToastProvider } from "@/components/ui/Toast";
import { chatApi } from "@/lib/chat";
import { CHAT_MODE_IS, CHAT_SET_MODE, emit } from "@/lib/chatBus";
import { displayName } from "@/lib/useUser";

const wrap = (ui: React.ReactNode) => render(<ThemeProvider><ToastProvider>{ui}</ToastProvider></ThemeProvider>);

beforeEach(() => {
  vi.spyOn(chatApi, "modes").mockResolvedValue([
    { command: "custom", kind: "custom", label: "Custom", description: "All apps" },
    { command: "workflow", kind: "workflow", label: "Workflow", description: "Build workflows" },
    { command: "notion", kind: "connector", label: "Notion", description: "Only Notion", connector: "notion" },
  ]);
  vi.spyOn(chatApi, "conversations").mockResolvedValue([
    { id: "a", title: "Today chat", created_at: new Date().toISOString(), preview: "Found 3 sheets" },
    { id: "b", title: "Old chat", created_at: "2020-01-01T00:00:00Z", preview: "" },
  ]);
});
afterEach(() => { vi.restoreAllMocks(); push.mockClear(); localStorage.clear(); document.documentElement.classList.remove("dark"); });

describe("displayName", () => {
  it("prefers the full name, else tidies the email", () => {
    expect(displayName("a@b.c", { full_name: "Ada Lovelace" })).toBe("Ada Lovelace");
    expect(displayName("ada.lovelace@x.com")).toBe("Ada Lovelace");
    expect(displayName(null)).toBe("there");
  });
});

describe("Sidebar", () => {
  it("has the main destinations in order and no chat list", async () => {
    wrap(<Sidebar />);
    const main = screen.getByRole("navigation", { name: "Main" });
    expect(within(main).getAllByRole("link").map((a) => a.textContent?.trim())).toEqual(["Home", "Connections", "Workflows", "Runs", "Memory", "Settings"]);
    expect(within(main).getByRole("link", { name: "Runs" })).toHaveAttribute("aria-current", "page");
    expect(chatApi.conversations).not.toHaveBeenCalled();
    expect(screen.queryByText("Today chat")).not.toBeInTheDocument();
  });

  it("lists the AI tools modes; from another page a mode opens the chat with it", async () => {
    wrap(<Sidebar />);
    const list = await screen.findByRole("list", { name: "Modes" });
    await waitFor(() => expect(within(list).getByText("/notion")).toBeInTheDocument());
    await userEvent.click(within(list).getByRole("button", { name: /\/workflow/ }));
    expect(push).toHaveBeenCalledWith("/chat?mode=workflow");
  });

  it("highlights the mode the chat reports", async () => {
    wrap(<Sidebar />);
    const list = await screen.findByRole("list", { name: "Modes" });
    await waitFor(() => expect(within(list).getByText("/notion")).toBeInTheDocument());
    emit(CHAT_MODE_IS, "notion");
    await waitFor(() => expect(within(list).getByRole("button", { name: /\/notion/ })).toHaveAttribute("aria-pressed", "true"));
    expect(CHAT_SET_MODE).toBe("chat:set-mode");
  });

  it("the user card shows the name and email, and the theme control persists the choice", async () => {
    wrap(<Sidebar />);
    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("ada.lovelace@x.com")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "Dark" }));
    expect(document.documentElement).toHaveClass("dark");
    expect(localStorage.getItem("theme")).toBe("dark");
    await userEvent.click(screen.getByRole("radio", { name: "Light" }));
    expect(document.documentElement).not.toHaveClass("dark");
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });
});

describe("HistoryPanel", () => {
  it("shows title, one-line preview and time, and filters with the search box", async () => {
    wrap(<HistoryPanel />);
    expect(await screen.findByText("Today chat")).toBeInTheDocument();
    expect(screen.getByText("Found 3 sheets")).toBeInTheDocument();
    expect(screen.getByText("just now")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Search chats"), "old");
    expect(screen.queryByText("Today chat")).not.toBeInTheDocument();
    expect(screen.getByText("Old chat")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Search chats"));
    await userEvent.type(screen.getByLabelText("Search chats"), "zzz");
    expect(screen.getByText("No chats match your search.")).toBeInTheDocument();
  });

  it("opens a chat on the chat page from another page, and Create new chat goes to /chat", async () => {
    wrap(<HistoryPanel />);
    await userEvent.click(await screen.findByText("Today chat"));
    expect(push).toHaveBeenCalledWith("/chat?c=a");
    await userEvent.click(screen.getByRole("button", { name: /Create new chat/ }));
    expect(push).toHaveBeenCalledWith("/chat");
  });

  it("renames a chat through the options menu and a dialog", async () => {
    const rename = vi.spyOn(chatApi, "rename").mockImplementation(async () => {
      vi.spyOn(chatApi, "conversations").mockResolvedValue([{ id: "a", title: "Plan", created_at: new Date().toISOString() }]);
      return { id: "a", title: "Plan" };
    });
    wrap(<HistoryPanel />);
    await screen.findByText("Today chat");
    await userEvent.click(screen.getByRole("button", { name: "Options for Today chat" }));
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    const input = screen.getByLabelText("Title");
    await userEvent.clear(input);
    await userEvent.type(input, "Plan");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(rename).toHaveBeenCalledWith("a", "Plan");
    expect(await screen.findByText("Plan")).toBeInTheDocument();
  });

  it("asks before deleting a chat", async () => {
    const remove = vi.spyOn(chatApi, "remove").mockResolvedValue({ ok: true });
    wrap(<HistoryPanel />);
    await screen.findByText("Today chat");
    await userEvent.click(screen.getByRole("button", { name: "Options for Today chat" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(remove).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("Delete this chat?");
    await userEvent.click(screen.getByRole("button", { name: "Delete chat" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("a"));
    await waitFor(() => expect(screen.queryByText("Today chat")).not.toBeInTheDocument());
  });
});
