"use client";

import { useId, useState, type ReactNode } from "react";
import {
  ArrowUp, CalendarDays, Check, ChevronRight, Mic, Paperclip, Search, Sliders, Sparkles, Square, Workflow,
} from "lucide-react";
import { Glyph, Kbd, LogoTile, MButton, MChip, MIconButton, Popover, Status, ThinkingDots, type Tone } from "@/components/min/ui";
import { MODES, ModeIcon, type ModeItem } from "@/components/min/Shell";

/* ---------- Home (empty state) ---------- */
const SUGGESTIONS = [
  { icon: Search, title: "Search my files", text: "Find a document, sheet or page across my connected apps.", prompt: "Search my files for the Q4 planning sheet" },
  { icon: Workflow, title: "Build a workflow", text: "Describe an automation and get a draft on the canvas.", prompt: "Build a workflow that posts new Stripe payments to Slack" },
  { icon: CalendarDays, title: "Check my calendar", text: "See what is coming up this week.", prompt: "What is on my calendar this week?" },
];

export function ChatHome({ name, onPick }: { name: string; onPick: (prompt: string) => void }) {
  return (
    <div className="mx-auto flex h-full max-w-2xl flex-col items-center justify-center px-6 pb-28 text-center">
      <Glyph size={64} />
      <h1 className="mt-8 text-[34px] font-semibold leading-tight tracking-tight">Welcome, {name}</h1>
      <p className="mt-2 text-sm text-m-muted">How can I help you today?</p>
      <ul aria-label="Suggestions" className="mt-10 grid w-full gap-3 sm:grid-cols-3">
        {SUGGESTIONS.map(({ icon: Icon, title, text, prompt }) => (
          <li key={title}>
            <button type="button" onClick={() => onPick(prompt)}
              className="h-full w-full rounded-2xl border border-m-line bg-m-panel p-4 text-left shadow-[var(--m-shadow)] transition-colors duration-150 hover:border-m-line-strong">
              <span className="flex size-8 items-center justify-center rounded-lg bg-m-accent-soft text-m-accent"><Icon size={16} strokeWidth={1.75} aria-hidden /></span>
              <span className="mt-4 block text-[13px] font-medium">{title}</span>
              <span className="mt-1 block text-xs leading-5 text-m-muted">{text}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ---------- Composer ---------- */
export function Composer({ value, onChange, mode, onMode, busy, memory, onMemory, model }: {
  value: string; onChange: (v: string) => void; mode: string; onMode: (command: string) => void; busy?: boolean;
  memory: boolean; onMemory: (v: boolean) => void; model: string;
}) {
  const [menu, setMenu] = useState<"mode" | "options" | null>(null);
  const inputId = useId();
  const slash = value.startsWith("/") && !value.includes(" ");
  const q = slash ? value.slice(1).toLowerCase() : "";
  const slashModes = slash ? MODES.filter((m) => m.command.includes(q) || m.label.toLowerCase().includes(q)) : [];
  const active = MODES.find((m) => m.command === mode) ?? MODES[0];

  function pick(m: ModeItem) {
    onMode(m.command);
    if (slash) onChange("");
    setMenu(null);
  }

  const list = (items: ModeItem[]) => (
    <ul role="listbox" aria-label="Modes" className="max-h-64 overflow-y-auto">
      {items.map((m) => (
        <li key={m.command} role="option" aria-selected={m.command === mode}>
          <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => pick(m)}
            className="flex h-9 w-full items-center gap-2.5 rounded-xl px-2.5 text-left text-[13px] hover:bg-m-soft">
            <span className="flex w-6 justify-center"><ModeIcon mode={m} /></span>
            <span className="font-mono text-xs">/{m.command}</span>
            <span className="flex-1 truncate text-xs text-m-muted">{m.kind === "custom" ? "All connected apps" : m.kind === "workflow" ? "Build workflows" : `Only ${m.label}`}</span>
            {m.command === mode && <Check size={13} aria-hidden className="text-m-accent" />}
          </button>
        </li>
      ))}
      {items.length === 0 && <li className="px-3 py-3 text-xs text-m-muted">No mode matches.</li>}
    </ul>
  );

  return (
    <div className="relative mx-auto w-full max-w-3xl px-6 pb-5">
      {slash && (
        <div className="m-in absolute inset-x-6 bottom-full mb-2 rounded-2xl border border-m-line bg-m-panel p-1.5 shadow-[var(--m-pop-shadow)]">{list(slashModes)}</div>
      )}
      <div className="rounded-2xl border border-m-line-strong bg-m-panel p-3 shadow-[var(--m-shadow)] transition-colors duration-150 focus-within:border-m-accent focus-within:ring-2 focus-within:ring-m-accent/20">
        <div className="flex items-start gap-2.5">
          <Sparkles size={16} strokeWidth={1.75} aria-hidden className="mt-2 shrink-0 text-m-muted" />
          <label htmlFor={inputId} className="sr-only">Message</label>
          <textarea id={inputId} rows={2} value={value} onChange={(e) => onChange(e.target.value)}
            placeholder="Ask anything, or type / for commands…"
            className="min-h-[48px] min-w-0 flex-1 resize-none bg-transparent py-1.5 text-sm leading-6 placeholder:text-m-muted focus:outline-none" />
        </div>
        <div className="mt-2 flex items-center gap-2">
          <MChip icon={Paperclip}>Attach</MChip>
          <div className="relative">
            <MChip aria-haspopup="listbox" aria-expanded={menu === "mode"} onClick={() => setMenu(menu === "mode" ? null : "mode")}
              leading={<span className="flex items-center"><ModeIcon mode={active} size={12} /></span>}>
              Mode <span className="font-mono text-m-text">/{active.command}</span>
            </MChip>
            <Popover open={menu === "mode"} onClose={() => setMenu(null)} label="Choose a mode" className="bottom-full left-0 mb-2 w-72">{list(MODES)}</Popover>
          </div>
          <div className="relative">
            <MChip icon={Sliders} aria-haspopup="dialog" aria-expanded={menu === "options"} onClick={() => setMenu(menu === "options" ? null : "options")}>Options</MChip>
            <Popover open={menu === "options"} onClose={() => setMenu(null)} label="Options" className="bottom-full left-0 mb-2 w-64 p-3">
              <p className="text-xs font-medium">Model</p>
              <p className="mt-1 rounded-lg border border-m-line bg-m-window px-2.5 py-1.5 font-mono text-xs">{model}</p>
              <label className="mt-3 flex cursor-pointer items-center justify-between text-[13px]">
                Memory
                <input type="checkbox" role="switch" checked={memory} onChange={(e) => onMemory(e.target.checked)}
                  className="relative h-5 w-9 cursor-pointer appearance-none rounded-full bg-m-line-strong transition-colors checked:bg-m-ink after:absolute after:left-0.5 after:top-0.5 after:size-4 after:rounded-full after:bg-m-panel after:transition-transform checked:after:translate-x-4" />
              </label>
              <p className="mt-1 text-[11px] text-m-muted">Remember short facts between chats.</p>
            </Popover>
          </div>
          <span className="ml-auto" />
          <MIconButton label="Voice input" icon={Mic} />
          {busy ? <MIconButton label="Stop generating" icon={Square} tone="ink" size={34} /> : <MIconButton label="Send" icon={ArrowUp} tone="ink" size={34} disabled={!value.trim()} />}
        </div>
      </div>
      <p className="mt-2 flex items-center justify-center gap-3 text-[11px] text-m-muted">
        <span><Kbd>↵</Kbd> send</span><span><Kbd>⇧↵</Kbd> new line</span><span><Kbd>/</Kbd> commands</span>
        <span>Memory {memory ? "on" : "off"}</span>
      </p>
    </div>
  );
}

/* ---------- Conversation ---------- */
export function UserBlock({ children }: { children: ReactNode }) {
  return <div className="flex justify-end"><p className="max-w-[80%] whitespace-pre-wrap rounded-2xl bg-m-soft px-4 py-2.5 text-sm leading-6">{children}</p></div>;
}

export function AssistantText({ children, streaming }: { children: ReactNode; streaming?: boolean }) {
  return <div className="space-y-2.5 text-sm leading-7">{children}{streaming && <span aria-hidden className="m-cursor" />}</div>;
}

const TONE: Record<"running" | "ok" | "error", { tone: Tone; text: string }> = {
  running: { tone: "info", text: "Running" }, ok: { tone: "ok", text: "Done" }, error: { tone: "bad", text: "Failed" },
};

export function ToolRow({ name, app, logo, status, duration, input, output, defaultOpen, error }: {
  name: string; app: string; logo: ReactNode; status: "running" | "ok" | "error"; duration?: string;
  input?: string; output?: string; defaultOpen?: boolean; error?: ReactNode;
}) {
  const [open, setOpen] = useState(Boolean(defaultOpen));
  const s = TONE[status];
  return (
    <div className="rounded-xl border border-m-line bg-m-panel">
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        className="flex h-10 w-full items-center gap-2.5 rounded-xl px-3 text-left transition-colors duration-150 hover:bg-m-soft">
        <LogoTile size={22}>{logo}</LogoTile>
        <span className="min-w-0 flex-1 truncate text-[13px]"><span className="text-m-muted">{app} · </span><span className="font-mono text-xs">{name}</span></span>
        {duration && <span className="font-mono text-[11px] text-m-muted">{duration}</span>}
        <Status tone={s.tone}>{s.text}</Status>
        <ChevronRight size={14} aria-hidden className={`text-m-muted transition-transform duration-150 ${open ? "rotate-90" : ""}`} />
      </button>
      {error && <p className="px-3 pb-3 text-[13px] text-m-bad">{error}</p>}
      {open && (input || output) && (
        <div className="space-y-3 border-t border-m-line p-3">
          {[["Input", input], ["Output", output]].map(([l, v]) => v && (
            <div key={l}>
              <p className="mb-1 text-[11px] font-medium text-m-muted">{l}</p>
              <pre className="max-h-40 overflow-auto rounded-lg bg-m-window p-2.5 font-mono text-xs leading-5">{v}</pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function ApprovalCard({ app, logo, action, risk, description, args }: {
  app: string; logo: ReactNode; action: string; risk: "write" | "destructive"; description: string; args: Record<string, string>;
}) {
  const [state, setState] = useState<"pending" | "approved" | "rejected">("pending");
  return (
    <section aria-label={`Approval needed: ${app} ${action}`} className="rounded-2xl border border-m-line-strong bg-m-panel p-4 shadow-[var(--m-shadow)]">
      <div className="flex items-center gap-2.5">
        <LogoTile size={26}>{logo}</LogoTile>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[13px] font-medium">{app} · {action}</h3>
          <p className="text-xs text-m-muted">{description}</p>
        </div>
        <Status tone={risk === "destructive" ? "bad" : "warn"}>{risk === "destructive" ? "Destructive" : "Needs approval"}</Status>
      </div>
      <dl className="mt-3 divide-y divide-m-line rounded-xl bg-m-window font-mono text-xs">
        {Object.entries(args).map(([k, v]) => (
          <div key={k} className="grid grid-cols-[7rem_1fr] gap-3 px-3 py-2"><dt className="text-m-muted">{k}</dt><dd className="break-all">{v}</dd></div>
        ))}
      </dl>
      <div className="mt-3 flex items-center gap-2">
        {state === "pending" ? (
          <>
            <MButton size="sm" icon={Check} onClick={() => setState("approved")}>Approve</MButton>
            <MButton size="sm" variant="secondary" onClick={() => setState("rejected")}>Reject</MButton>
            <span className="ml-auto text-[11px] text-m-muted">Nothing happens until you approve.</span>
          </>
        ) : <p role="status" className="text-[13px] font-medium">{state === "approved" ? "Approved" : "Rejected"}</p>}
      </div>
    </section>
  );
}

export { ThinkingDots };
