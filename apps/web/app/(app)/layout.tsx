import type { ReactNode } from "react";
import { AppShell } from "@/components/shell/AppShell";

// Access is gated in proxy.ts; every API call is re-verified by FastAPI.
export default function AppLayout({ children }: { children: ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
