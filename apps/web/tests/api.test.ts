import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: vi.fn() }));

import { ApiError, apiFetch } from "@/lib/api";

afterEach(() => vi.unstubAllGlobals());

describe("apiFetch", () => {
  it("sends the Supabase access token as a bearer header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "u1" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const out = await apiFetch<{ id: string }>("/api/me", {}, async () => "jwt-abc");
    expect(out).toEqual({ id: "u1" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/me");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer jwt-abc");
  });

  it("throws ApiError with the API detail", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "invalid token" }), { status: 401 }),
    ));
    await expect(apiFetch("/api/me", {}, async () => null)).rejects.toMatchObject({
      status: 401, message: "invalid token",
    });
    await expect(apiFetch("/api/me", {}, async () => null)).rejects.toBeInstanceOf(ApiError);
  });
});
