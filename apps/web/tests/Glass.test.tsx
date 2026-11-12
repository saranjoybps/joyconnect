import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/client", () => ({
  getSupabaseBrowserClient: () => ({ auth: { getSession: async () => ({ data: { session: { user: { id: "u1" } } } }) } }),
}));

import { ThemeProvider, useTheme } from "@/components/ui/theme";
import { Tabs } from "@/components/ui/Tabs";

function Probe() {
  const { pref, setPref } = useTheme();
  return <button type="button" onClick={() => setPref("dark")}>{pref}</button>;
}

afterEach(() => { localStorage.clear(); document.documentElement.classList.remove("dark"); });

describe("theme", () => {
  it("saves the choice per user and applies the dark class", async () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    await userEvent.click(screen.getByRole("button", { name: "system" }));
    await waitFor(() => expect(document.documentElement).toHaveClass("dark"));
    expect(localStorage.getItem("theme")).toBe("dark");
    await waitFor(() => expect(localStorage.getItem("theme:u1")).toBe("dark"));
  });

  it("restores that user's own saved choice", async () => {
    localStorage.setItem("theme:u1", "dark");
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(await screen.findByRole("button", { name: "dark" })).toBeInTheDocument();
    await waitFor(() => expect(document.documentElement).toHaveClass("dark"));
  });
});

describe("Tabs", () => {
  it("selects with click and arrow keys", async () => {
    const onChange = vi.fn();
    render(<Tabs label="Filter" value="a" onChange={onChange} tabs={[{ id: "a", label: "A" }, { id: "b", label: "B" }]} />);
    expect(screen.getByRole("tab", { name: "A" })).toHaveAttribute("aria-selected", "true");
    await userEvent.click(screen.getByRole("tab", { name: "B" }));
    expect(onChange).toHaveBeenLastCalledWith("b");
    screen.getByRole("tab", { name: "A" }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenLastCalledWith("b");
  });
});
