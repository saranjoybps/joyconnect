"use client";

import { useEffect, useState } from "react";
import { apiFetch, type Me } from "@/lib/api";

export function ChatPlaceholder() {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<Me>("/api/me").then(setMe, (e: Error) => setError(e.message));
  }, []);

  return (
    <section aria-labelledby="chat-title" className="space-y-3">
      <h1 id="chat-title" className="text-xl font-semibold">Chat</h1>
      {error && <p role="alert" className="text-red-600">Could not reach the API: {error}</p>}
      {me && <p className="text-sm text-neutral-500">Signed in as {me.email ?? me.id} (verified by the API).</p>}
      <p className="text-neutral-600 dark:text-neutral-400">The assistant arrives in Phase 2.</p>
    </section>
  );
}
