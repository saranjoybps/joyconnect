import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({ default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a> }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: vi.fn() }));

import { ActionCard } from "@/components/ActionCard";
import { ChatWindow } from "@/components/ChatWindow";
import { Markdown } from "@/components/Markdown";
import { applyEvent, chatApi } from "@/lib/chat";
import { connectionsApi } from "@/lib/connections";
import { parseMarkdown } from "@/lib/format";

async function* stream(...events: { event: string; data: unknown }[]) {
  for (const e of events) yield e;
}
const done = { event: "done", data: { conversation_id: "c1" } };

describe("Markdown", () => {
  const md = "| Name | Qty |\n| --- | --- |\n| Ada | 2 |\n| Bob | [x](https://x.test) |\n\n```python\nprint(1)\n```";

  it("parses tables and fenced code languages", () => {
    const blocks = parseMarkdown(md);
    expect(blocks[0]).toMatchObject({ t: "table" });
    expect(blocks[1]).toEqual({ t: "code", v: "print(1)", lang: "python" });
  });

  it("renders a table with headers and clickable links, and a code block with a copy button", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<Markdown text={md} />);
    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Ada" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "x" })).toHaveAttribute("href", "https://x.test");
    expect(screen.getByRole("link", { name: "x" })).toHaveAttribute("rel", "noopener noreferrer");
    await userEvent.click(screen.getByRole("button", { name: "Copy code" }));
    expect(writeText).toHaveBeenCalledWith("print(1)");
    expect(await screen.findByText("Copied")).toBeInTheDocument();
  });
});

describe("tool events", () => {
  it("carry input, output and duration into the card", () => {
    let items = applyEvent([], { event: "tool_call", data: { id: "c1", tool: "notion__search", connector: "notion", connector_name: "Notion", label: "Search", input: { query: "roadmap" } } });
    items = applyEvent(items, { event: "tool_result", data: { id: "c1", tool: "notion__search", ok: true, output: "{\"n\":1}", duration_ms: 420 } });
    expect(items[0]).toMatchObject({ status: "ok", input: { query: "roadmap" }, output: "{\"n\":1}", duration_ms: 420, connector: "notion" });
  });

  it("memory events become a Memory used marker", () => {
    expect(applyEvent([], { event: "memory", data: { count: 2 } })).toEqual([{ kind: "memory", count: 2 }]);
  });
});

describe("ActionCard timeline", () => {
  it("shows status and duration, and reveals input and output on demand", async () => {
    render(<ol><ActionCard label="Notion · Search" status="ok" durationMs={1500} input={{ query: "roadmap" }} output='{"n":1}' /></ol>);
    expect(screen.getByText("1.5 s")).toBeInTheDocument();
    expect(screen.queryByText("Input")).not.toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: /Show details/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(screen.getByText("Input")).toBeInTheDocument();
    expect(screen.getByText(/roadmap/)).toBeInTheDocument();
    expect(screen.getByText("Output")).toBeInTheDocument();
  });

  it("failed calls offer Reconnect for auth errors and Retry otherwise", async () => {
    const retry = vi.fn();
    const { rerender } = render(<ol><ActionCard label="Sheets" status="error" summary="boom" onRetry={retry} /></ol>);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalled();
    rerender(<ol><ActionCard label="Sheets" status="error" summary="x" action={{
      id: "1", connector: "google_sheets", connector_name: "Google Sheets", tool: "t", label: "l", ok: false,
      result: "Token expired", link: null, error_kind: "auth" }} /></ol>);
    expect(screen.getByRole("link", { name: "Reconnect Google Sheets" })).toHaveAttribute("href", "/connections");
    expect(screen.getByRole("alert")).toHaveTextContent("Token expired");
  });
});

describe("ChatWindow composer", () => {
  beforeEach(() => {
    vi.spyOn(chatApi, "modes").mockResolvedValue([{ command: "custom", kind: "custom", label: "Custom", description: "All apps" }]);
    vi.spyOn(connectionsApi, "list").mockResolvedValue([{ id: "c", status: "active" }] as never);
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows suggested prompts on an empty chat that fill the composer", async () => {
    render(<ChatWindow />);
    const box = await screen.findByRole("combobox", { name: "Message" });
    await userEvent.click(await screen.findByRole("button", { name: /Search my files/ }));
    expect(box).toHaveValue("Search my files for the Q4 planning sheet");
  });

  it("Enter sends and Shift+Enter inserts a new line", async () => {
    const send = vi.spyOn(chatApi, "send").mockReturnValue(stream({ event: "token", data: { text: "Hi" } }, done));
    render(<ChatWindow />);
    const box = await screen.findByRole("combobox", { name: "Message" });
    await userEvent.type(box, "line one{Shift>}{Enter}{/Shift}line two");
    expect(box).toHaveValue("line one\nline two");
    expect(send).not.toHaveBeenCalled();
    await userEvent.type(box, "{Enter}");
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Hi")).toBeInTheDocument();
  });

  it("shows Stop while streaming and aborts the request", async () => {
    let signal: AbortSignal | undefined;
    vi.spyOn(chatApi, "send").mockImplementation((_m, _c, _mode, s) => {
      signal = s;
      return (async function* () {
        yield { event: "token", data: { text: "Working" } };
        await new Promise((_r, rej) => s?.addEventListener("abort", () => rej(Object.assign(new Error("aborted"), { name: "AbortError" }))));
      })();
    });
    render(<ChatWindow />);
    await userEvent.type(await screen.findByRole("combobox", { name: "Message" }), "go{Enter}");
    const stop = await screen.findByRole("button", { name: "Stop generating" });
    await userEvent.click(stop);
    await waitFor(() => expect(signal?.aborted).toBe(true));
    expect(await screen.findByRole("button", { name: "Send" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();   // a stop is not an error
    expect(screen.getByText("Working")).toBeInTheDocument();
  });

  it("links Memory used to the Memory page", async () => {
    vi.spyOn(chatApi, "send").mockReturnValue(stream({ event: "memory", data: { count: 2 } }, { event: "token", data: { text: "Sure" } }, done));
    render(<ChatWindow />);
    await userEvent.type(await screen.findByRole("combobox", { name: "Message" }), "hi{Enter}");
    expect(await screen.findByRole("link", { name: /Memory used/ })).toHaveAttribute("href", "/memory");
  });

  it("regenerate rewinds the last user message and resends it", async () => {
    vi.spyOn(chatApi, "send").mockImplementation(() => stream({ event: "token", data: { text: "Answer" } }, done));
    const rewind = vi.spyOn(chatApi, "rewind").mockResolvedValue({ ok: true, text: "hi", removed: 2 });
    render(<ChatWindow />);
    await userEvent.type(await screen.findByRole("combobox", { name: "Message" }), "hi{Enter}");
    await userEvent.click(await screen.findByRole("button", { name: /Regenerate/ }));
    await waitFor(() => expect(rewind).toHaveBeenCalledWith("c1", 0));
    await waitFor(() => expect(chatApi.send).toHaveBeenCalledTimes(2));
    expect(chatApi.send).toHaveBeenLastCalledWith("hi", "c1", "custom", expect.any(AbortSignal));
  });

  it("edit and resend rewinds to that message and sends the new text", async () => {
    vi.spyOn(chatApi, "send").mockImplementation(() => stream({ event: "token", data: { text: "Answer" } }, done));
    const rewind = vi.spyOn(chatApi, "rewind").mockResolvedValue({ ok: true, text: "hi", removed: 2 });
    render(<ChatWindow />);
    await userEvent.type(await screen.findByRole("combobox", { name: "Message" }), "hi{Enter}");
    await userEvent.click(await screen.findByRole("button", { name: "Edit and resend" }));
    const edit = screen.getByLabelText("Edit message");
    await userEvent.clear(edit);
    await userEvent.type(edit, "hello again");
    await userEvent.click(screen.getByRole("button", { name: "Save and resend" }));
    await waitFor(() => expect(rewind).toHaveBeenCalledWith("c1", 0));
    await waitFor(() => expect(chatApi.send).toHaveBeenLastCalledWith("hello again", "c1", "custom", expect.any(AbortSignal)));
  });
});
