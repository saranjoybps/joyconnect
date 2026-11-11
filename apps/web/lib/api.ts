"use client";

import { env } from "@/lib/env";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export type TokenGetter = () => Promise<string | null>;

const defaultTokenGetter: TokenGetter = async () => {
  const { data } = await getSupabaseBrowserClient().auth.getSession();
  return data.session?.access_token ?? null;
};

/** Calls FastAPI with the user's Supabase access token. Never sends provider tokens. */
export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  getToken: TokenGetter = defaultTokenGetter,
): Promise<T> {
  const token = await getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const resp = await fetch(`${env.apiBaseUrl}${path}`, { ...init, headers });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(resp.status, detail);
  }
  return (resp.status === 204 ? undefined : await resp.json()) as T;
}

export type Me = { id: string; email: string | null };
