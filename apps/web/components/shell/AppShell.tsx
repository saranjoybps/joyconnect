"use client";

import { Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/shell/Sidebar";
import { IconButton } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Card";
import { CloseIcon, LogoMark, MenuIcon } from "@/components/ui/icons";

const KEY = "sidebar-collapsed";

function MobileClose({ onClose }: { onClose: () => void }) {
  // Close the drawer after any navigation.
  const pathname = usePathname();
  const first = useRef(pathname);
  useEffect(() => { if (first.current !== pathname) onClose(); }, [pathname]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

function Nav({ collapsed, toggle }: { collapsed: boolean; toggle: () => void }) {
  return <Sidebar collapsed={collapsed} onToggleCollapsed={toggle} />;
}

export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [drawer, setDrawer] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- browser-only preference, read after mount
    try { setCollapsed(localStorage.getItem(KEY) === "1"); } catch { /* default: expanded */ }
  }, []);
  function toggle() {
    setCollapsed((c) => {
      try { localStorage.setItem(KEY, c ? "0" : "1"); } catch { /* not persisted */ }
      return !c;
    });
  }

  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setDrawer(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawer]);

  return (
    <div className="flex min-h-dvh">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-accent focus:px-3 focus:py-2 focus:text-accent-fg">
        Skip to content
      </a>

      {/* Desktop sidebar */}
      <aside aria-label="Sidebar"
        className={`glass sticky top-0 hidden h-dvh shrink-0 rounded-none border-y-0 border-l-0 transition-[width] duration-200 md:block ${collapsed ? "w-16" : "w-72"}`}>
        {/* usePathname() is runtime data on dynamic routes, so the navigation streams in. */}
        <Suspense fallback={<div className="p-4"><Skeleton className="h-8 w-full" /></div>}>
          <Nav collapsed={collapsed} toggle={toggle} />
        </Suspense>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-2 glass rounded-none border-x-0 border-t-0 px-3 md:hidden">
          <IconButton label="Open menu" onClick={() => setDrawer(true)}><MenuIcon /></IconButton>
          <span className="flex items-center gap-2 font-semibold tracking-tight"><LogoMark /> Connect</span>
        </header>
        <main id="main" tabIndex={-1} className="min-w-0 flex-1 focus:outline-none">{children}</main>
      </div>

      {/* Mobile drawer */}
      {drawer && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div aria-hidden className="absolute inset-0 bg-[#0a0f24]/45" onClick={() => setDrawer(false)} />
          <aside role="dialog" aria-modal="true" aria-label="Navigation" className="anim-fade-up glass-strong absolute inset-y-0 left-0 w-[min(20rem,85vw)] rounded-none border-y-0 border-l-0">
            <div className="absolute right-2 top-3 z-10">
              <IconButton label="Close menu" onClick={() => setDrawer(false)}><CloseIcon /></IconButton>
            </div>
            <Suspense fallback={null}>
              <Sidebar collapsed={false} mobile onToggleCollapsed={() => undefined} onNavigate={() => setDrawer(false)} />
              <MobileClose onClose={() => setDrawer(false)} />
            </Suspense>
          </aside>
        </div>
      )}
    </div>
  );
}
