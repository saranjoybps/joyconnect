import { describe, expect, it } from "vitest";
import { timeAgo } from "@/lib/connections";

describe("timeAgo", () => {
  const now = new Date("2026-11-12T12:00:00Z");
  it("formats recent times", () => {
    expect(timeAgo(null, now)).toBe("never");
    expect(timeAgo("2026-11-12T11:59:40Z", now)).toBe("just now");
    expect(timeAgo("2026-11-12T11:55:00Z", now)).toBe("5 min ago");
    expect(timeAgo("2026-11-12T09:00:00Z", now)).toBe("3 h ago");
  });
});
