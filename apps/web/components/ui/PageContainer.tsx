import type { ReactNode } from "react";

/** Standard page width and spacing for every non-chat page. */
export function PageContainer({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return <div className={`mx-auto w-full px-4 py-8 sm:px-8 sm:py-12 ${wide ? "max-w-7xl" : "max-w-5xl"}`}>{children}</div>;
}
