"use client";

import { Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { History, Menu, X } from "lucide-react";
import { HistoryPanel } from "@/components/shell/HistoryPanel";
import { Sidebar } from "@/components/shell/Sidebar";
import { IconButton } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Card";

const KEY = "history-open";
const TITLES: [string, string][] = [
  ["/chat", "Home"], ["/connections", "Connections"], ["/workflows", "Workflows"], ["/runs", "Runs"], ["/memory", "Memory"], ["/settings", "Settings"],
];

/** Page title (and, on the chat page, the history toggle). usePathname() is runtime data, so this streams in. */
function Header({ historyVisible, onToggleHistory, onMenu }: { historyVisible: boolean; onToggleHistory: () => void; onMenu: () => void }) {
  const pathname = usePathname() ?? "";
  const title = TITLES.find(([p]) => pathname === p || pathname.startsWith(`${p}/`))?.[1] ?? "";
  const onChat = pathname.startsWith("/chat");
  return (
    <header className="flex h-12 shrink-0 items-center gap-2 px-4 sm:px-5">
      <IconButton label="Open menu" className="md:hidden" onClick={onMenu}><Menu size={16} strokeWidth={1.75} aria-hidden /></IconButton>
      <h2 className="flex-1 text-[13px] font-medium text-m-muted">{title}</h2>
      {onChat && (
        <IconButton label={historyVisible ? "Hide chat history" : "Show chat history"} aria-expanded={historyVisible} aria-controls="chat-history"
          onClick={onToggleHistory}><History size={16} strokeWidth={1.75} aria-hidden /></IconButton>
      )}
    </header>
  );
}

function HistorySlot({ open, setOpen }: { open: boolean | null; setOpen: (v: boolean) => void }) {
  const pathname = usePathname() ?? "";
  if (!pathname.startsWith("/chat")) return null;
  // null = default: hidden on small screens, shown from the lg breakpoint up. An explicit choice wins.
  const vis = open === null ? "hidden lg:block" : open ? "block" : "hidden";
  return (
    <div id="chat-history" className={`${vis} absolute inset-y-2 right-2 z-20 w-72 lg:static lg:inset-auto lg:z-auto lg:w-auto lg:p-2.5 lg:pl-0`}>
      <HistoryPanel onNavigate={() => { if (open) setOpen(false); }} />
    </div>
  );
}

function MobileClose({ onClose }: { onClose: () => void }) {
  const pathname = usePathname();
  const first = useRef(pathname);
  useEffect(() => { if (first.current !== pathname) onClose(); }, [pathname]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

/** The large rounded full-screen window: slim sidebar, content, optional history panel on the right. */
export function AppShell({ children }: { children: ReactNode }) {
  const [historyOpen, setHistoryOpen] = useState<boolean | null>(null);
  const [lg, setLg] = useState(false);
  const [drawer, setDrawer] = useState(false);

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- browser-only preferences, read after mount */
    try { const v = localStorage.getItem(KEY); if (v === "1" || v === "0") setHistoryOpen(v === "1"); } catch { /* default */ }
    if (typeof matchMedia !== "function") return;
    const mq = matchMedia("(min-width: 1024px)");
    setLg(mq.matches);
    /* eslint-enable react-hooks/set-state-in-effect */
    const on = () => setLg(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);

  const visible = historyOpen ?? lg;
  function setOpen(v: boolean) {
    setHistoryOpen(v);
    try { localStorage.setItem(KEY, v ? "1" : "0"); } catch { /* not persisted */ }
  }

  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setDrawer(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawer]);

  return (
    <div className="min-h-dvh bg-m-window">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-full focus:bg-m-ink focus:px-3 focus:py-2 focus:text-m-ink-fg">
        Skip to content
      </a>
      <div className="relative flex h-dvh overflow-hidden bg-m-window text-m-text">
        <aside aria-label="Sidebar" className="hidden w-56 shrink-0 border-r border-m-line md:flex">
          <Suspense fallback={<div className="w-full p-4"><Skeleton className="h-8 w-full" /></div>}>
            <Sidebar />
          </Suspense>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <Suspense fallback={<div className="h-12 shrink-0" />}>
            <Header historyVisible={visible} onToggleHistory={() => setOpen(!visible)} onMenu={() => setDrawer(true)} />
          </Suspense>
          <main id="main" tabIndex={-1} className="relative min-h-0 min-w-0 flex-1 overflow-y-auto focus:outline-none">{children}</main>
        </div>

        <Suspense fallback={null}>
          <HistorySlot open={historyOpen} setOpen={setOpen} />
        </Suspense>

        {drawer && (
          <div className="fixed inset-0 z-40 md:hidden">
            <div aria-hidden className="absolute inset-0 bg-[var(--m-overlay)]" onClick={() => setDrawer(false)} />
            <aside role="dialog" aria-modal="true" aria-label="Navigation" className="m-in absolute inset-y-0 left-0 w-[min(18rem,85vw)] border-r border-m-line bg-m-window">
              <div className="absolute right-2 top-3 z-10">
                <IconButton label="Close menu" onClick={() => setDrawer(false)}><X size={16} strokeWidth={1.75} aria-hidden /></IconButton>
              </div>
              <Suspense fallback={null}>
                <Sidebar onNavigate={() => setDrawer(false)} />
                <MobileClose onClose={() => setDrawer(false)} />
              </Suspense>
            </aside>
          </div>
        )}
      </div>
    </div>
  );
}
