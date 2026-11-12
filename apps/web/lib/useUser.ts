"use client";

import { useEffect, useState } from "react";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

export type CurrentUser = { name: string; firstName: string; email: string | null };

/** Display name from the account: full name if set, else the part of the email before the "@". */
export function displayName(email: string | null, meta?: Record<string, unknown> | null): string {
  const full = (meta?.full_name ?? meta?.name) as unknown;
  if (typeof full === "string" && full.trim()) return full.trim();
  const local = (email ?? "").split("@")[0].replace(/[._-]+/g, " ").trim();
  if (!local) return "there";
  return local.replace(/\b\w/g, (c) => c.toUpperCase());
}

/** The signed-in user for the greeting and the sidebar user card. Falls back to a neutral guest. */
export function useUser(): CurrentUser {
  const [user, setUser] = useState<CurrentUser>({ name: "Account", firstName: "there", email: null });
  useEffect(() => {
    let alive = true;
    try {
      Promise.resolve(getSupabaseBrowserClient().auth.getSession()).then((r) => {
        const u = r?.data?.session?.user;
        if (!alive || !u) return;
        const name = displayName(u.email ?? null, u.user_metadata as Record<string, unknown> | undefined);
        setUser({ name, firstName: name.split(" ")[0], email: u.email ?? null });
      }, () => undefined);
    } catch { /* no session in isolated renders */ }
    return () => { alive = false; };
  }, []);
  return user;
}
