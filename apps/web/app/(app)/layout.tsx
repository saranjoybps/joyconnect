import type { ReactNode } from "react";
import { AppNav } from "@/components/AppNav";

// Access is gated in proxy.ts; every API call is re-verified by FastAPI.
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-dvh">
      <AppNav />
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
