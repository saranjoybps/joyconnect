"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Brain, ChevronDown, GitBranch, Home, LogOut, Monitor, Moon, Play, Plug, Settings, Sparkles, Sun, Workflow } from "lucide-react";
import { BrandMark } from "@/components/ui/BrandLogo";
import { IconButton } from "@/components/ui/Button";
import { Glyph, LogoTile } from "@/components/ui/kit";
import { useTheme, type ThemePref } from "@/components/ui/theme";
import { chatApi } from "@/lib/chat";
import { CHAT_MODE_IS, CHAT_SET_MODE, emit, on } from "@/lib/chatBus";
import { DEFAULT_MODE, type ChatMode } from "@/lib/modes";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { useUser } from "@/lib/useUser";

const NAV = [
  { href: "/chat", label: "Home", Icon: Home },
  { href: "/connections", label: "Connections", Icon: Plug },
  { href: "/workflows", label: "Workflows", Icon: Workflow },
  { href: "/runs", label: "Runs", Icon: Play },
  { href: "/memory", label: "Memory", Icon: Brain },
  { href: "/settings", label: "Settings", Icon: Settings },
];

export function ModeGlyph({ mode, size = 14 }: { mode: ChatMode; size?: number }) {
  if (mode.kind === "connector" && mode.connector) {
    const mark = BrandMark({ id: mode.connector, name: mode.label, size: size - 2 });
    return <LogoTile size={size + 6}>{mark ?? <span className="text-[10px] font-semibold text-[#161620]">{mode.label.charAt(0)}</span>}</LogoTile>;
  }
  const Icon = mode.kind === "workflow" ? GitBranch : Sparkles;
  return <Icon size={size} strokeWidth={1.75} aria-hidden className="text-m-muted" />;
}

export function ThemeToggle() {
  const { pref, setPref } = useTheme();
  const items: { id: ThemePref; label: string; Icon: typeof Sun }[] = [
    { id: "light", label: "Light", Icon: Sun }, { id: "dark", label: "Dark", Icon: Moon }, { id: "system", label: "System", Icon: Monitor },
  ];
  return (
    <div role="radiogroup" aria-label="Theme" className="inline-flex rounded-full border border-m-line bg-m-soft p-0.5">
      {items.map(({ id, label, Icon }) => (
        <button key={id} type="button" role="radio" aria-checked={pref === id} aria-label={label} title={label} onClick={() => setPref(id)}
          className={`flex size-6 items-center justify-center rounded-full transition-colors duration-150 ${pref === id ? "bg-m-panel text-m-text shadow-[var(--m-shadow)]" : "text-m-muted hover:text-m-text"}`}>
          <Icon size={13} strokeWidth={1.75} aria-hidden />
        </button>
      ))}
    </div>
  );
}

/** Slim icon + label navigation, the "AI tools" modes, and the user card. Chats are NOT listed here (see HistoryPanel). */
export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname() ?? "";
  const router = useRouter();
  const user = useUser();
  const [toolsOpen, setToolsOpen] = useState(true);
  const [modes, setModes] = useState<ChatMode[]>([DEFAULT_MODE]);
  const [active, setActive] = useState("custom");

  useEffect(() => {
    let alive = true;
    chatApi.modes().then((m) => alive && setModes(m), () => undefined);
    return () => { alive = false; };
  }, []);
  useEffect(() => on<string>(CHAT_MODE_IS, setActive), []);

  function pickMode(m: ChatMode) {
    setActive(m.command);
    if (pathname.startsWith("/chat")) emit(CHAT_SET_MODE, m.command);
    else router.push(`/chat?mode=${encodeURIComponent(m.command)}`);
    onNavigate?.();
  }

  async function signOut() {
    await getSupabaseBrowserClient().auth.signOut();
    router.replace("/login");
    router.refresh();
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col px-3 pb-3 pt-5">
      <Link href="/chat" onClick={onNavigate} className="flex items-center gap-2 rounded-full px-2 pb-6">
        <Glyph size={22} />
        <span className="text-[15px] font-semibold tracking-tight">Connect</span>
      </Link>

      <nav aria-label="Main" className="space-y-0.5">
        {NAV.map(({ href, label, Icon }) => {
          const on = href === "/chat" ? pathname.startsWith("/chat") : pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link key={href} href={href} onClick={onNavigate} aria-current={on ? "page" : undefined}
              className={`flex h-9 items-center gap-2.5 rounded-full px-3 text-[13px] transition-colors duration-150 ${on ? "bg-m-panel font-medium text-m-text shadow-[var(--m-shadow)]" : "text-m-muted hover:bg-m-soft hover:text-m-text"}`}>
              <Icon size={16} strokeWidth={1.75} aria-hidden />{label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-6 min-h-0 flex-1 overflow-y-auto">
        <button type="button" aria-expanded={toolsOpen} onClick={() => setToolsOpen((o) => !o)}
          className="flex h-8 w-full items-center justify-between rounded-full px-3 text-xs font-medium">
          AI tools <ChevronDown size={14} aria-hidden className={`text-m-muted transition-transform duration-150 ${toolsOpen ? "" : "-rotate-90"}`} />
        </button>
        {toolsOpen && (
          <ul aria-label="Modes" className="mt-1 space-y-0.5">
            {modes.map((m) => (
              <li key={m.command}>
                <button type="button" aria-pressed={active === m.command} onClick={() => pickMode(m)} title={m.description}
                  className={`flex h-8 w-full items-center gap-2.5 rounded-full px-3 text-[13px] transition-colors duration-150 ${active === m.command ? "bg-m-soft text-m-text" : "text-m-muted hover:bg-m-soft hover:text-m-text"}`}>
                  <span className="flex w-5 justify-center"><ModeGlyph mode={m} size={13} /></span>
                  <span className="truncate font-mono text-xs">/{m.command}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="mt-3 rounded-2xl border border-m-line bg-m-panel p-2.5 shadow-[var(--m-shadow)]">
        <div className="flex items-center gap-2.5">
          <span aria-hidden className="flex size-8 shrink-0 items-center justify-center rounded-full bg-m-ink text-xs font-semibold text-m-ink-fg">
            {user.name.charAt(0).toUpperCase()}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-medium leading-4">{user.name}</p>
            <p className="truncate text-[11px] leading-4 text-m-muted">{user.email ?? ""}</p>
          </div>
          <IconButton label="Sign out" className="size-7" onClick={signOut}><LogOut size={14} strokeWidth={1.75} aria-hidden /></IconButton>
        </div>
        <div className="mt-2.5 flex items-center justify-between">
          <span className="text-[11px] text-m-muted">Theme</span>
          <ThemeToggle />
        </div>
      </div>
    </div>
  );
}
