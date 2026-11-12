"use client";

import { useState, type ReactNode } from "react";
import {
  Brain, ChevronDown, GitBranch, History, Home, Monitor, Moon, Play, Plug, Settings, Sparkles, Sun, Workflow,
} from "lucide-react";
import { Glyph, LogoTile, MIconButton } from "@/components/min/ui";
import { BrandMark } from "@/components/ui/BrandLogo";

export type Theme = "light" | "dark";
export type ThemePref = "system" | "light" | "dark";

export type ModeItem = { command: string; label: string; kind: "custom" | "workflow" | "connector"; connector?: string };
export const MODES: ModeItem[] = [
  { command: "custom", label: "Custom", kind: "custom" },
  { command: "workflow", label: "Workflow", kind: "workflow" },
  { command: "google-sheets", label: "Google Sheets", kind: "connector", connector: "google_sheets" },
  { command: "notion", label: "Notion", kind: "connector", connector: "notion" },
  { command: "github", label: "GitHub", kind: "connector", connector: "github" },
  { command: "linear", label: "Linear", kind: "connector", connector: "linear" },
];

export function ModeIcon({ mode, size = 14 }: { mode: ModeItem; size?: number }) {
  if (mode.kind === "connector" && mode.connector) {
    const m = BrandMark({ id: mode.connector, name: mode.label, size: size - 2 });
    return <LogoTile size={size + 6}>{m}</LogoTile>;
  }
  const Icon = mode.kind === "workflow" ? GitBranch : Sparkles;
  return <Icon size={size} strokeWidth={1.75} aria-hidden className="text-m-muted" />;
}

export type NavId = "home" | "connections" | "workflows" | "runs" | "memory" | "settings";
const NAV: { id: NavId; label: string; icon: typeof Home }[] = [
  { id: "home", label: "Home", icon: Home },
  { id: "connections", label: "Connections", icon: Plug },
  { id: "workflows", label: "Workflows", icon: Workflow },
  { id: "runs", label: "Runs", icon: Play },
  { id: "memory", label: "Memory", icon: Brain },
  { id: "settings", label: "Settings", icon: Settings },
];

export function ThemeToggle({ pref, onChange }: { pref: ThemePref; onChange: (p: ThemePref) => void }) {
  const items: { id: ThemePref; label: string; icon: typeof Sun }[] = [
    { id: "light", label: "Light", icon: Sun }, { id: "dark", label: "Dark", icon: Moon }, { id: "system", label: "System", icon: Monitor },
  ];
  return (
    <div role="radiogroup" aria-label="Theme" className="inline-flex rounded-full border border-m-line bg-m-soft p-0.5">
      {items.map(({ id, label, icon: Icon }) => (
        <button key={id} type="button" role="radio" aria-checked={pref === id} aria-label={label} title={label} onClick={() => onChange(id)}
          className={`flex size-6 items-center justify-center rounded-full transition-colors duration-150 ${pref === id ? "bg-m-panel text-m-text shadow-[var(--m-shadow)]" : "text-m-muted hover:text-m-text"}`}>
          <Icon size={13} strokeWidth={1.75} aria-hidden />
        </button>
      ))}
    </div>
  );
}

export function Sidebar({ active, onNavigate, mode, onMode, user, pref, onPref }: {
  active: NavId; onNavigate: (id: NavId) => void; mode: string; onMode: (command: string) => void;
  user: { name: string; email: string }; pref: ThemePref; onPref: (p: ThemePref) => void;
}) {
  const [toolsOpen, setToolsOpen] = useState(true);
  return (
    <aside aria-label="Sidebar" className="flex w-56 shrink-0 flex-col border-r border-m-line px-3 pb-3 pt-5">
      <div className="flex items-center gap-2 px-2 pb-6">
        <Glyph size={22} />
        <span className="text-[15px] font-semibold tracking-tight">Connect</span>
      </div>

      <nav aria-label="Main" className="space-y-0.5">
        {NAV.map(({ id, label, icon: Icon }) => (
          <button key={id} type="button" aria-current={active === id ? "page" : undefined} onClick={() => onNavigate(id)}
            className={`flex h-9 w-full items-center gap-2.5 rounded-full px-3 text-[13px] transition-colors duration-150 ${active === id ? "bg-m-panel font-medium text-m-text shadow-[var(--m-shadow)]" : "text-m-muted hover:bg-m-soft hover:text-m-text"}`}>
            <Icon size={16} strokeWidth={1.75} aria-hidden />{label}
          </button>
        ))}
      </nav>

      <div className="mt-6 min-h-0 flex-1 overflow-y-auto">
        <button type="button" aria-expanded={toolsOpen} onClick={() => setToolsOpen((o) => !o)}
          className="flex h-8 w-full items-center justify-between rounded-full px-3 text-xs font-medium text-m-text">
          AI tools <ChevronDown size={14} aria-hidden className={`text-m-muted transition-transform duration-150 ${toolsOpen ? "" : "-rotate-90"}`} />
        </button>
        {toolsOpen && (
          <ul aria-label="Modes" className="mt-1 space-y-0.5">
            {MODES.map((m) => (
              <li key={m.command}>
                <button type="button" aria-pressed={mode === m.command} onClick={() => onMode(m.command)}
                  className={`flex h-8 w-full items-center gap-2.5 rounded-full px-3 text-[13px] transition-colors duration-150 ${mode === m.command ? "bg-m-soft text-m-text" : "text-m-muted hover:bg-m-soft hover:text-m-text"}`}>
                  <span className="flex w-5 justify-center"><ModeIcon mode={m} size={13} /></span>
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
            {user.name.charAt(0)}
          </span>
          <div className="min-w-0">
            <p className="truncate text-[13px] font-medium leading-4">{user.name}</p>
            <p className="truncate text-[11px] leading-4 text-m-muted">{user.email}</p>
          </div>
        </div>
        <div className="mt-2.5 flex items-center justify-between">
          <span className="text-[11px] text-m-muted">Theme</span>
          <ThemeToggle pref={pref} onChange={onPref} />
        </div>
      </div>
    </aside>
  );
}

/** The large rounded window floating on the gradient page. The history panel is a separate right column. */
export function AppWindow({ theme, sidebar, children, history, historyOpen, onToggleHistory, title }: {
  theme: Theme; sidebar: ReactNode; children: ReactNode; history?: ReactNode; historyOpen: boolean;
  onToggleHistory: () => void; title: string;
}) {
  return (
    <div className={`${theme} m-page rounded-[28px] p-3 sm:p-6`} data-theme-panel={theme}>
      <div className="relative flex h-[720px] overflow-hidden rounded-[24px] border border-m-line bg-m-window text-m-text shadow-[var(--m-window-shadow)]">
        <div className="hidden md:flex">{sidebar}</div>
        <div className="relative flex min-w-0 flex-1 flex-col">
          <header className="flex h-12 shrink-0 items-center justify-between px-5">
            <h2 className="text-[13px] font-medium text-m-muted">{title}</h2>
            <MIconButton label={historyOpen ? "Hide chat history" : "Show chat history"} icon={History}
              aria-expanded={historyOpen} onClick={onToggleHistory} />
          </header>
          <div className="relative min-h-0 flex-1">{children}</div>
        </div>
        {history && historyOpen && (
          <div className="absolute inset-y-2 right-2 z-20 w-72 lg:static lg:inset-auto lg:z-auto lg:w-auto lg:p-2.5 lg:pl-0">{history}</div>
        )}
      </div>
    </div>
  );
}
