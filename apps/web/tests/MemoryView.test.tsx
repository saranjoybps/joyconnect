import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: vi.fn() }));

import { MemoryView } from "@/components/MemoryView";
import { ApiError } from "@/lib/api";
import { memoryApi, type Memory, type MemoryList } from "@/lib/memory";
import { isProtectedPath } from "@/lib/routes";

const mem = (over: Partial<Memory> = {}): Memory => ({
  id: "m1", kind: "fact", content: "The user's name is Sam.", created_at: null, updated_at: null, ...over,
});
const list = (memories: Memory[], enabled = true): MemoryList => ({
  enabled, kinds: ["fact", "preference", "task", "identifier"], memories,
});

afterEach(() => vi.restoreAllMocks());

describe("MemoryView", () => {
  it("lists what is remembered, with its kind", async () => {
    vi.spyOn(memoryApi, "list").mockResolvedValue(
      list([mem(), mem({ id: "m2", kind: "preference", content: "Prefers bullet points." })]),
    );
    render(<MemoryView />);
    expect(await screen.findByText("The user's name is Sam.")).toBeInTheDocument();
    expect(screen.getAllByText("Preference").length).toBeGreaterThan(1); // badge + the select option
  });

  it("shows an empty state", async () => {
    vi.spyOn(memoryApi, "list").mockResolvedValue(list([]));
    render(<MemoryView />);
    expect(await screen.findByText(/Nothing remembered yet/)).toBeInTheDocument();
  });

  it("adds a memory and reloads", async () => {
    const listSpy = vi.spyOn(memoryApi, "list").mockResolvedValue(list([]));
    const add = vi.spyOn(memoryApi, "add").mockResolvedValue(mem());
    render(<MemoryView />);
    await screen.findByText(/Nothing remembered yet/);
    await userEvent.type(screen.getByLabelText("New memory"), "My main sheet is Test Leads.");
    await userEvent.click(screen.getByRole("button", { name: "Add memory" }));
    await waitFor(() => expect(add).toHaveBeenCalledWith("My main sheet is Test Leads.", "fact"));
    await waitFor(() => expect(listSpy).toHaveBeenCalledTimes(2));
  });

  it("edits a memory", async () => {
    vi.spyOn(memoryApi, "list").mockResolvedValue(list([mem()]));
    const update = vi.spyOn(memoryApi, "update").mockResolvedValue(mem({ content: "The user's name is Samuel." }));
    render(<MemoryView />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const input = screen.getByLabelText("Edit memory");
    await userEvent.clear(input);
    await userEvent.type(input, "The user's name is Samuel.");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(update).toHaveBeenCalledWith("m1", { content: "The user's name is Samuel." }));
  });

  it("deletes one memory and all memories", async () => {
    vi.spyOn(memoryApi, "list").mockResolvedValue(list([mem()]));
    const remove = vi.spyOn(memoryApi, "remove").mockResolvedValue(undefined);
    const removeAll = vi.spyOn(memoryApi, "removeAll").mockResolvedValue({ deleted: 1 });
    render(<MemoryView />);
    await userEvent.click(await screen.findByRole("button", { name: /Delete memory/ }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("m1"));
    await userEvent.click(screen.getByRole("button", { name: "Delete all memories" }));
    await userEvent.click(await screen.findByRole("button", { name: "Yes, delete everything" }));
    await waitFor(() => expect(removeAll).toHaveBeenCalled());
  });

  it("turns memory off and says what that means", async () => {
    vi.spyOn(memoryApi, "list").mockResolvedValueOnce(list([mem()])).mockResolvedValue(list([mem()], false));
    const set = vi.spyOn(memoryApi, "setEnabled").mockResolvedValue({ memory_enabled: false });
    render(<MemoryView />);
    await userEvent.click(await screen.findByRole("switch"));
    await waitFor(() => expect(set).toHaveBeenCalledWith(false));
    expect(await screen.findByText(/Memory is off: nothing new is saved/)).toBeInTheDocument();
  });

  it("shows the API error, e.g. when the migration is missing", async () => {
    vi.spyOn(memoryApi, "list").mockRejectedValue(new ApiError(503, "Memory is not available yet."));
    render(<MemoryView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Memory is not available yet.");
  });

  it("is a protected route", () => {
    expect(isProtectedPath("/memory")).toBe(true);
  });
});
