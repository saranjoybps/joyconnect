import { Suspense, type ReactNode } from "react";
import { AppNav } from "@/components/AppNav";

// Access is gated in proxy.ts; every API call is re-verified by FastAPI.
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-dvh">
      {/* usePathname() is runtime data on dynamic routes such as /workflows/[id], so the nav streams in. */}
      <Suspense fallback={<header className="h-[3.25rem] border-b border-neutral-200 dark:border-neutral-800" />}>
        <AppNav />
      </Suspense>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
