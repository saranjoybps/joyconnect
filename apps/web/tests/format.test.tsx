import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: vi.fn() }));

import { ActionCard } from "@/components/ActionCard";
import { Markdown } from "@/components/Markdown";
import { applyEvent, itemsFromDetail, type Action } from "@/lib/chat";
import { displayText, parseInline, parseMarkdown } from "@/lib/format";

const action = (over: Partial<Action> = {}): Action => ({
  id: "c1", connector: "google_sheets", connector_name: "Google Sheets", tool: "google_sheets__create_spreadsheet",
  label: "Create spreadsheet", ok: true, result: "Leads", link: "https://docs.google.com/spreadsheets/d/abc",
  error_kind: null, ...over,
});

describe("parseMarkdown", () => {
  it("handles bold labels, bullets, headings and links", () => {
    const blocks = parseMarkdown("Created your sheet.\n\n- **Sheet:** [Leads](https://x.test/a)\n- **Rows:** 2\n\n1. one\n2. two");
    expect(blocks.map((b) => b.t)).toEqual(["p", "ul", "ol"]);
    const ul = blocks[1] as { items: unknown[][] };
    expect(ul.items).toHaveLength(2);
    expect(ul.items[0]).toEqual([
      { t: "bold", v: "Sheet:" }, { t: "text", v: " " }, { t: "link", v: "Leads", href: "https://x.test/a" },
    ]);
  });

  it("never makes an anchor from a non-http link", () => {
    const parts = parseInline("[click](javascript:alert(1)) and https://ok.test/x");
    expect(parts.some((p) => p.t === "link" && p.href.startsWith("javascript"))).toBe(false);
    expect(parts.some((p) => p.t === "link" && p.href === "https://ok.test/x")).toBe(true);
  });
});

describe("displayText fallback", () => {
  it("leaves Markdown alone", () => expect(displayText("**Done** - ok")).toBe("**Done** - ok"));
  it("uses the prose field of a JSON reply", () => expect(displayText('{"summary":"Added a row."}')).toBe("Added a row."));
  it("never shows raw JSON", () => {
    const shown = displayText('{"rows":[1,2],"x":{"y":1}}');
    expect(shown).not.toMatch(/[{}[\]]/);
  });
  it("shows invalid JSON-looking text as written", () => expect(displayText("[not json")).toBe("[not json"));
});

describe("Markdown component", () => {
  it("renders formatted output with a clickable link", () => {
    render(<Markdown text={"Done.\n\n- **Sheet:** [Leads](https://docs.google.com/spreadsheets/d/abc)"} />);
    expect(screen.getByText("Sheet:").tagName).toBe("STRONG");
    const link = screen.getByRole("link", { name: "Leads" });
    expect(link).toHaveAttribute("href", "https://docs.google.com/spreadsheets/d/abc");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });
  it("does not render raw JSON", () => {
    render(<Markdown text={'{"a":1}'} />);
    expect(screen.queryByText(/"a"/)).toBeNull();
  });
});

describe("ActionCard", () => {
  it("shows the result and a link to the created item", () => {
    render(<ActionCard label="Google Sheets · Create spreadsheet" status="ok" action={action()} />);
    expect(screen.getByText("Leads")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open/i })).toHaveAttribute("href", "https://docs.google.com/spreadsheets/d/abc");
  });
  it("offers Reconnect for auth/scope errors", () => {
    render(<ActionCard label="Sheets" status="error" action={action({ ok: false, link: null, error_kind: "scope", result: "Permission missing" })} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Permission missing");
    expect(screen.getByRole("link", { name: /reconnect google sheets/i })).toHaveAttribute("href", "/connections");
  });
  it("offers Retry for other errors", async () => {
    const onRetry = vi.fn();
    render(<ActionCard label="Slack" status="error" summary="boom" onRetry={onRetry}
      action={action({ ok: false, link: null, error_kind: "server", result: "Could not reach Slack" })} />);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});

describe("chat reducer carries the action", () => {
  it("stores the validated action from tool_result and from a reloaded conversation", () => {
    const a = action();
    const items = applyEvent([], { event: "tool_result", data: { id: "c1", tool: a.tool, ok: true, action: a } });
    expect(items[0]).toMatchObject({ kind: "tool", status: "ok", action: a });
    const re = itemsFromDetail({ id: "x", title: null, pending_approvals: [],
      items: [{ kind: "tool", id: "c1", tool: a.tool, ok: true, summary: null, action: a }] });
    expect(re[0]).toMatchObject({ action: a });
  });
});
