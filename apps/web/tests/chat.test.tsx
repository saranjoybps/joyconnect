import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: vi.fn() }));

import { ApprovalPrompt } from "@/components/ApprovalPrompt";
import { applyEvent, itemsFromDetail, labelFor, type ApprovalPreview, type ChatItem } from "@/lib/chat";
import { readSse } from "@/lib/sse";

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      chunks.forEach((ch) => c.enqueue(enc.encode(ch)));
      c.close();
    },
  });
}

describe("readSse", () => {
  it("parses events split across chunks", async () => {
    const out = [];
    for await (const ev of readSse(streamOf('event: token\ndata: {"te', 'xt":"Hi"}\n\nevent: done\r\n', 'data: {}\r\n\r\n'))) {
      out.push(ev);
    }
    expect(out).toEqual([{ event: "token", data: { text: "Hi" } }, { event: "done", data: {} }]);
  });
});

const approval: ApprovalPreview = {
  approval_id: "a1", tool_call_id: "c1", conversation_id: "conv", tool: "google_sheets__append_row",
  connector: "google_sheets", connector_name: "Google Sheets", account: "me@x.com", action: "Append row",
  description: "Append one row", risk: "write", args: { range: "Sheet1!A:B", values: ["Ada", "ada@x.com"] },
};

describe("applyEvent", () => {
  it("streams tokens into one assistant message", () => {
    let items: ChatItem[] = [{ kind: "user", text: "hi" }];
    items = applyEvent(items, { event: "token", data: { text: "Hel" } });
    items = applyEvent(items, { event: "token", data: { text: "lo" } });
    expect(items).toEqual([{ kind: "user", text: "hi" }, { kind: "assistant", text: "Hello" }]);
  });

  it("tracks a tool call from running to done", () => {
    let items: ChatItem[] = [];
    items = applyEvent(items, { event: "tool_call", data: { id: "c1", tool: "notion__search", connector_name: "Notion", label: "Search" } });
    expect(items[0]).toMatchObject({ kind: "tool", label: "Notion · Search", status: "running" });
    items = applyEvent(items, { event: "tool_result", data: { id: "c1", tool: "notion__search", ok: false, summary: "boom" } });
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ status: "error", summary: "boom" });
  });

  it("adds approval cards and errors", () => {
    let items = applyEvent([], { event: "approval_required", data: approval });
    items = applyEvent(items, { event: "error", data: { message: "down" } });
    expect(items[0]).toMatchObject({ kind: "approval", state: "pending" });
    expect(items[1]).toEqual({ kind: "error", text: "down" });
  });

  it("rebuilds the transcript with pending approvals", () => {
    const items = itemsFromDetail({
      id: "conv", title: "t", pending_approvals: [approval],
      items: [{ kind: "user", text: "add" }, { kind: "tool", id: "x", tool: "slack__list_channels", ok: true, summary: null }],
    });
    expect(items.map((i) => i.kind)).toEqual(["user", "tool", "approval"]);
    expect(labelFor("slack__list_channels")).toBe("List channels");
  });
});

describe("ApprovalPrompt", () => {
  it("shows the preview and reports the decision", async () => {
    const onDecide = vi.fn();
    render(<ApprovalPrompt approval={approval} state="pending" onDecide={onDecide} />);
    expect(screen.getByRole("heading", { name: /Google Sheets · Append row/ })).toBeInTheDocument();
    expect(screen.getByText("Sheet1!A:B")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(onDecide).toHaveBeenCalledWith(false);
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(onDecide).toHaveBeenLastCalledWith(true);
  });

  it("hides buttons after a decision", () => {
    render(<ApprovalPrompt approval={approval} state="approved" onDecide={() => undefined} />);
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Approved");
  });
});
