import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { MinPreview } from "@/components/min/MinPreview";

function win(i: number) {
  return within(document.querySelectorAll<HTMLElement>("[data-theme-panel]")[i]);
}

describe("minimal design preview", () => {
  it("shows three screens, each in the chosen theme(s)", async () => {
    render(<MinPreview />);
    expect(document.querySelectorAll("[data-theme-panel]")).toHaveLength(3);
    await userEvent.click(screen.getByRole("tab", { name: "Both" }));
    expect(document.querySelectorAll("[data-theme-panel]")).toHaveLength(6);
    expect(document.querySelectorAll("[data-theme-panel='dark']")).toHaveLength(3);
  });

  it("sidebar has the main destinations and the AI tools modes, and no chat list", () => {
    render(<MinPreview />);
    const side = win(0);
    const nav = side.getAllByRole("navigation", { name: "Main" })[0];
    expect(within(nav).getAllByRole("button").map((b) => b.textContent)).toEqual(["Home", "Connections", "Workflows", "Runs", "Memory", "Settings"]);
    expect(side.getAllByRole("list", { name: "Modes" })[0]).toBeInTheDocument();
    expect(side.getAllByText("/google-sheets").length).toBeGreaterThan(0);
    // the chat titles live only in the separate Chat history panel
    const sidebar = side.getAllByRole("complementary", { name: "Sidebar" })[0];
    expect(within(sidebar).queryByText("Q4 leads sheet")).not.toBeInTheDocument();
  });

  it("history panel searches and offers a rename/delete menu and Create new chat", async () => {
    render(<MinPreview />);
    const w = win(0);
    expect(w.getByRole("heading", { name: "Chat history" })).toBeInTheDocument();
    await userEvent.type(w.getByLabelText("Search chats"), "stripe");
    expect(w.getByText("Stripe payments digest")).toBeInTheDocument();
    expect(w.queryByText("Q4 leads sheet")).not.toBeInTheDocument();
    await userEvent.click(w.getByRole("button", { name: "Options for Stripe payments digest" }));
    expect(w.getByRole("button", { name: "Rename" })).toBeInTheDocument();
    expect(w.getByRole("button", { name: "Delete" })).toBeInTheDocument();
    expect(w.getByRole("button", { name: /Create new chat/ })).toBeInTheDocument();
  });

  it("a suggestion card fills the composer, and / opens the command list", async () => {
    render(<MinPreview />);
    const w = win(0);
    await userEvent.click(w.getByRole("button", { name: /Check my calendar/ }));
    const box = w.getByRole("textbox", { name: "Message" });
    expect(box).toHaveValue("What is on my calendar this week?");
    await userEvent.clear(box);
    await userEvent.type(box, "/");
    expect(w.getAllByRole("option").length).toBeGreaterThanOrEqual(6);
  });

  it("the conversation has a collapsible tool row and an inline approval card", async () => {
    render(<MinPreview />);
    const w = win(1);
    expect(w.getByRole("region", { name: /Approval needed/ })).toBeInTheDocument();
    const row = w.getByRole("button", { name: /search_files/ });
    expect(row).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(row);
    expect(row).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(w.getByRole("button", { name: "Approve" }));
    expect(w.getByRole("status", { name: "" })).toBeDefined();
  });

  it("the Connections grid lists Connected apps first", () => {
    render(<MinPreview />);
    const w = win(2);
    const names = w.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(names.slice(1, 4).sort()).toEqual(["Google Drive", "Google Sheets", "Linear"]);
  });
});
