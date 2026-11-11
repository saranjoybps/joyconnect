import { describe, expect, it } from "vitest";
import { isProtectedPath, safeNextPath } from "@/lib/routes";

describe("isProtectedPath", () => {
  it.each(["/chat", "/chat/123", "/connections", "/connections?x=1".split("?")[0]])("protects %s", (p) => {
    expect(isProtectedPath(p)).toBe(true);
  });
  it.each(["/login", "/", "/chatter", "/auth/callback"])("does not protect %s", (p) => {
    expect(isProtectedPath(p)).toBe(false);
  });
});

describe("safeNextPath", () => {
  it("keeps relative paths", () => expect(safeNextPath("/connections?connected=slack")).toBe("/connections?connected=slack"));
  it.each([null, "", "https://evil.com", "//evil.com", "/\\evil.com", "javascript:alert(1)"])(
    "falls back to /chat for %s",
    (v) => expect(safeNextPath(v)).toBe("/chat"),
  );
});
