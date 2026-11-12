import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: vi.fn() }));

import { ChatWindow } from "@/components/ChatWindow";
import { chatApi } from "@/lib/chat";
import { connectionsApi } from "@/lib/connections";
import { exactMode, filterModes, nextIndex, slashQuery, type ChatMode } from "@/lib/modes";

const MODES: ChatMode[] = [
  { command: "custom", kind: "custom", label: "Custom", description: "All apps" },
  { command: "workflow", kind: "workflow", label: "Workflow", description: "Build workflows" },
  { command: "google-docs", kind: "connector", label: "Google Docs", description: "Only Google Docs", aliases: ["docs"], connector: "google_docs" },
  { command: "google-sheets", kind: "connector", label: "Google Sheets", description: "Only Google Sheets", aliases: ["sheets"], connector: "google_sheets" },
  { command: "trello", kind: "connector", label: "Trello", description: "Only Trello", connector: "trello" },
];

async function* stream(...events: { event: string; data: unknown }[]) {
  for (const e of events) yield e;
}

beforeEach(() => {
  vi.spyOn(chatApi, "conversations").mockResolvedValue([]);
  vi.spyOn(chatApi, "modes").mockResolvedValue(MODES);
  vi.spyOn(connectionsApi, "list").mockResolvedValue([{ id: "c", status: "active" }] as never);
});
afterEach(() => vi.restoreAllMocks());

async function ready() {
  render(<ChatWindow />);
  const box = await screen.findByRole("combobox", { name: "Message" });
  await waitFor(() => expect(chatApi.modes).toHaveBeenCalled());
  return box;
}
const chip = () => screen.getByTestId("mode-chip");
const options = () => within(screen.getByRole("listbox", { name: "Chat modes" })).getAllByRole("option").map((o) => o.textContent ?? "");

describe("slash menu", () => {
  it("shows /custom as the default mode in a chip above the input", async () => {
    await ready();
    expect(chip()).toHaveTextContent("/custom");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("typing / opens a menu with /custom, /workflow and one command per connected app", async () => {
    const box = await ready();
    await userEvent.type(box, "/");
    const items = options();
    expect(items).toHaveLength(5);
    expect(items[0]).toContain("/custom");
    expect(items[1]).toContain("/workflow");
    expect(items.some((t) => t.includes("/google-docs"))).toBe(true);
    expect(items.some((t) => t.includes("/google-sheets"))).toBe(true);
    expect(items.some((t) => t.includes("/trello"))).toBe(true);
    expect(box).toHaveAttribute("aria-expanded", "true");
  });

  it("filters as you type, including short aliases like /sheets", async () => {
    const box = await ready();
    await userEvent.type(box, "/she");
    expect(options()).toEqual([expect.stringContaining("/google-sheets")]);
    await userEvent.clear(box);
    await userEvent.type(box, "/tre");
    expect(options()).toEqual([expect.stringContaining("/trello")]);
  });

  it("arrow keys move the highlight and Enter picks it: chip updates, input clears, menu closes, nothing is sent", async () => {
    const send = vi.spyOn(chatApi, "send");
    const box = await ready();
    await userEvent.type(box, "/");
    expect(screen.getByRole("option", { selected: true })).toHaveTextContent("/custom");
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("option", { selected: true })).toHaveTextContent("/workflow");
    await userEvent.keyboard("{ArrowDown}{ArrowDown}");
    expect(screen.getByRole("option", { selected: true })).toHaveTextContent("/google-sheets");
    await userEvent.keyboard("{ArrowUp}{ArrowUp}");
    expect(screen.getByRole("option", { selected: true })).toHaveTextContent("/workflow");
    await userEvent.keyboard("{Enter}");
    expect(chip()).toHaveTextContent("/workflow");
    expect(box).toHaveValue("");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(send).not.toHaveBeenCalled();
  });

  it("the highlight wraps around at both ends", async () => {
    const box = await ready();
    await userEvent.type(box, "/");
    await userEvent.keyboard("{ArrowUp}");
    expect(screen.getByRole("option", { selected: true })).toHaveTextContent("/trello");
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("option", { selected: true })).toHaveTextContent("/custom");
  });

  it("Esc closes the menu and keeps what was typed", async () => {
    const box = await ready();
    await userEvent.type(box, "/tr");
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(box).toHaveValue("/tr");
    expect(chip()).toHaveTextContent("/custom");
  });

  it("clicking an option picks it", async () => {
    const box = await ready();
    await userEvent.type(box, "/");
    await userEvent.click(screen.getByRole("option", { name: /\/trello/ }));
    expect(chip()).toHaveTextContent("/trello");
    expect(box).toHaveValue("");
  });

  it("does not open for ordinary text or once a space follows the command", async () => {
    const box = await ready();
    await userEvent.type(box, "hello /x");
    expect(screen.queryByRole("listbox")).toBeNull();
    await userEvent.clear(box);
    await userEvent.type(box, "/trello list boards");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("a mode other than /custom can be cleared from the chip", async () => {
    const box = await ready();
    await userEvent.type(box, "/");
    await userEvent.click(screen.getByRole("option", { name: /\/trello/ }));
    await userEvent.click(screen.getByRole("button", { name: "Back to /custom" }));
    expect(chip()).toHaveTextContent("/custom");
  });
});

describe("sending in a mode", () => {
  it("sends the chosen mode with the message", async () => {
    const send = vi.spyOn(chatApi, "send").mockReturnValue(stream({ event: "done", data: { conversation_id: "c1" } }));
    const box = await ready();
    await userEvent.type(box, "/");
    await userEvent.click(screen.getByRole("option", { name: /\/trello/ }));
    await userEvent.type(box, "list my boards{Enter}");
    await waitFor(() => expect(send).toHaveBeenCalledWith("list my boards", null, "trello"));
  });

  it("sends /custom by default", async () => {
    const send = vi.spyOn(chatApi, "send").mockReturnValue(stream({ event: "done", data: { conversation_id: "c1" } }));
    const box = await ready();
    await userEvent.type(box, "hello{Enter}");
    await waitFor(() => expect(send).toHaveBeenCalledWith("hello", null, "custom"));
  });

  it("typing a bare command and pressing Enter (menu dismissed) switches mode without sending", async () => {
    const send = vi.spyOn(chatApi, "send");
    const box = await ready();
    await userEvent.type(box, "/sheets");
    await userEvent.keyboard("{Escape}{Enter}");
    expect(send).not.toHaveBeenCalled();
    expect(chip()).toHaveTextContent("/google-sheets");
    expect(box).toHaveValue("");
  });

  it("follows the mode the server reports", async () => {
    vi.spyOn(chatApi, "send").mockReturnValue(
      stream({ event: "mode", data: { command: "workflow", kind: "workflow", connector: null } }, { event: "done", data: { conversation_id: "c1" } }),
    );
    const box = await ready();
    await userEvent.type(box, "/workflow plan a report{Enter}");
    await waitFor(() => expect(chip()).toHaveTextContent("/workflow"));
  });

  it("opening an old conversation restores its mode", async () => {
    vi.spyOn(chatApi, "conversations").mockResolvedValue([{ id: "c9", title: "Boards", created_at: "2026-11-12T10:00:00Z" }]);
    vi.spyOn(chatApi, "conversation").mockResolvedValue({
      id: "c9", title: "Boards", items: [{ kind: "user", text: "hi" }], pending_approvals: [],
      mode: { command: "trello", kind: "connector", connector: "trello" },
    });
    await ready();
    await userEvent.click(await screen.findByRole("button", { name: "Boards" }));
    await waitFor(() => expect(chip()).toHaveTextContent("/trello"));
  });
});

describe("mode helpers", () => {
  it("slashQuery only matches a command still being typed", () => {
    expect(slashQuery("/")).toBe("");
    expect(slashQuery("/Goo")).toBe("goo");
    expect(slashQuery("/a b")).toBeNull();
    expect(slashQuery("a/")).toBeNull();
    expect(slashQuery("")).toBeNull();
  });
  it("filterModes puts prefix matches first", () => {
    expect(filterModes(MODES, "g").map((m) => m.command)).toEqual(["google-docs", "google-sheets"]);
    expect(filterModes(MODES, "sheets").map((m) => m.command)).toEqual(["google-sheets"]);
    expect(filterModes(MODES, "ocs").map((m) => m.command)).toEqual(["google-docs"]);
    expect(filterModes(MODES, "zzz")).toEqual([]);
  });
  it("exactMode accepts commands and aliases", () => {
    expect(exactMode(MODES, "/docs")?.command).toBe("google-docs");
    expect(exactMode(MODES, "/trello")?.command).toBe("trello");
    expect(exactMode(MODES, "/trello x")).toBeNull();
  });
  it("nextIndex wraps", () => {
    expect(nextIndex("ArrowDown", 4, 5)).toBe(0);
    expect(nextIndex("ArrowUp", 0, 5)).toBe(4);
    expect(nextIndex("ArrowDown", 0, 0)).toBe(0);
  });
});
