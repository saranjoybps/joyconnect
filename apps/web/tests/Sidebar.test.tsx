import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn() }), usePathname: () => "/runs" }));
vi.mock("next/link", () => ({ default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a> }));
vi.mock("@/lib/supabase/client", () => ({
  getSupabaseBrowserClient: () => ({ auth: { getSession: async () => ({ data: { session: { user: { email: "me@x.com" } } } }), signOut: vi.fn() } }),
}));

import { Sidebar } from "@/components/shell/Sidebar";
import { ThemeProvider } from "@/components/ui/theme";
import { ToastProvider } from "@/components/ui/Toast";
import { chatApi } from "@/lib/chat";
import { groupByDate } from "@/lib/groupByDate";

const NOW = new Date("2026-11-12T15:00:00");
const iso = (daysAgo: number) => new Date(NOW.getTime() - daysAgo * 86_400_000).toISOString();

function renderSidebar(collapsed = false) {
  const toggle = vi.fn();
  render(<ThemeProvider><ToastProvider><Sidebar collapsed={collapsed} onToggleCollapsed={toggle} /></ToastProvider></ThemeProvider>);
  return toggle;
}

beforeEach(() => {
  vi.spyOn(chatApi, "conversations").mockResolvedValue([
    { id: "a", title: "Today chat", created_at: new Date().toISOString() },
    { id: "b", title: "Old chat", created_at: "2020-01-01T00:00:00Z" },
  ]);
});
afterEach(() => { vi.restoreAllMocks(); push.mockClear(); document.documentElement.classList.remove("dark"); });

describe("groupByDate", () => {
  it("buckets by age, newest first, omitting empty groups", () => {
    const rows = [
      { id: 1, created_at: iso(40) }, { id: 2, created_at: iso(0) }, { id: 3, created_at: iso(1) },
      { id: 4, created_at: iso(3) }, { id: 5, created_at: iso(15) },
    ];
    const g = groupByDate(rows, NOW);
    expect(g.map((x) => x.label)).toEqual(["Today", "Yesterday", "Previous 7 days", "Previous 30 days", "Older"]);
    expect(g.map((x) => x.items[0].id)).toEqual([2, 3, 4, 5, 1]);
    expect(groupByDate([], NOW)).toEqual([]);
  });
});

describe("Sidebar", () => {
  it("has the main destinations in order", async () => {
    renderSidebar();
    const main = screen.getByRole("navigation", { name: "Main" });
    expect(within(main).getAllByRole("link").map((a) => a.textContent?.trim())).toEqual(["Connections", "Workflows", "Runs", "Memory", "Settings"]);
    expect(within(main).getByRole("link", { name: "Runs" })).toHaveAttribute("aria-current", "page");
    await screen.findByText("Today chat");
  });

  it("groups chat history by date and filters it with the search box", async () => {
    renderSidebar();
    await screen.findByText("Today chat");
    expect(screen.getByRole("region", { name: "Today" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Older" })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Search chats"), "old");
    expect(screen.queryByText("Today chat")).not.toBeInTheDocument();
    expect(screen.getByText("Old chat")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Search chats"));
    await userEvent.type(screen.getByLabelText("Search chats"), "zzz");
    expect(screen.getByText("No chats match your search.")).toBeInTheDocument();
  });

  it("opens a chat on the chat page from another page, and New chat goes to /chat", async () => {
    renderSidebar();
    await userEvent.click(await screen.findByText("Today chat"));
    expect(push).toHaveBeenCalledWith("/chat?c=a");
    await userEvent.click(screen.getByRole("button", { name: "New chat" }));
    expect(push).toHaveBeenCalledWith("/chat");
  });

  it("renames a chat through a dialog", async () => {
    const rename = vi.spyOn(chatApi, "rename").mockImplementation(async () => {
      vi.spyOn(chatApi, "conversations").mockResolvedValue([{ id: "a", title: "Plan", created_at: new Date().toISOString() }]);
      return { id: "a", title: "Plan" };
    });
    renderSidebar();
    await screen.findByText("Today chat");
    await userEvent.click(screen.getByRole("button", { name: "Rename Today chat" }));
    const input = screen.getByLabelText("Title");
    await userEvent.clear(input);
    await userEvent.type(input, "Plan");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(rename).toHaveBeenCalledWith("a", "Plan");
    expect(await screen.findByText("Plan")).toBeInTheDocument();
  });

  it("asks before deleting a chat", async () => {
    const remove = vi.spyOn(chatApi, "remove").mockResolvedValue({ ok: true });
    renderSidebar();
    await screen.findByText("Today chat");
    await userEvent.click(screen.getByRole("button", { name: "Delete Today chat" }));
    expect(remove).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("Delete this chat?");
    await userEvent.click(screen.getByRole("button", { name: "Delete chat" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("a"));
    await waitFor(() => expect(screen.queryByText("Today chat")).not.toBeInTheDocument());
  });

  it("toggles dark mode and persists the choice", async () => {
    renderSidebar();
    await userEvent.click(screen.getByRole("button", { name: "Switch to dark mode" }));
    expect(document.documentElement).toHaveClass("dark");
    expect(localStorage.getItem("theme")).toBe("dark");
    await userEvent.click(screen.getByRole("button", { name: "Switch to light mode" }));
    expect(document.documentElement).not.toHaveClass("dark");
  });

  it("collapses to icon-only with accessible names and an expand button", () => {
    const toggle = renderSidebar(true);
    expect(screen.getByRole("link", { name: "Connections" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Search chats")).not.toBeInTheDocument();
    return userEvent.click(screen.getByRole("button", { name: "Expand sidebar" })).then(() => expect(toggle).toHaveBeenCalled());
  });

  it("the user menu shows the account and Sign out", async () => {
    renderSidebar();
    await userEvent.click(screen.getByRole("button", { name: "User menu" }));
    expect(await screen.findByText("me@x.com", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Sign out" })).toBeInTheDocument();
  });
});
