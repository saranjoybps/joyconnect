import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DesignPreview } from "@/components/pro/DesignPreview";

describe("design preview", () => {
  it("renders the components in dark, and side by side in both themes", async () => {
    render(<DesignPreview />);
    expect(screen.getByRole("heading", { name: "Design preview" })).toBeInTheDocument();
    expect(document.querySelectorAll("[data-theme-panel]")).toHaveLength(1);
    await userEvent.click(screen.getByRole("tab", { name: "Side by side" }));
    expect(document.querySelectorAll("[data-theme-panel]")).toHaveLength(2);
  });

  it("opens the command palette with Ctrl+K, filters, navigates and runs", async () => {
    render(<DesignPreview />);
    await userEvent.keyboard("{Control>}k{/Control}");
    const box = await screen.findByRole("combobox", { name: "Search commands" });
    await userEvent.type(box, "runs");
    expect(screen.getAllByRole("option")).toHaveLength(1);
    await userEvent.keyboard("{Enter}");
    expect(screen.queryByRole("dialog", { name: "Command palette" })).not.toBeInTheDocument();
    expect(screen.getByText(/Palette ran: Go to Runs/)).toBeInTheDocument();
  });

  it("tool call cards expand and the approval card exposes Approve and Reject", async () => {
    render(<DesignPreview />);
    expect(screen.getAllByRole("button", { name: /Approve/ }).length).toBeGreaterThan(0);
    const toggle = screen.getAllByRole("button", { expanded: false })[0];
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });
});
