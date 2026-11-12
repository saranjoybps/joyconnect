"use client";

import { useState, type ReactNode } from "react";
import {
  ArrowUp, Brain, Check, ChevronRight, Circle, Copy, Cpu, Loader2, Search, ShieldCheck, Sparkles, Square, Wrench,
} from "lucide-react";
import { Float, Kbd, LogoTile, PBadge, PButton, PIconButton, type Tone } from "@/components/pro/ui";

/* ---------- Messages ---------- */
export function UserMessage({ children }: { children: ReactNode }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[80%] whitespace-pre-wrap rounded-xl rounded-br-sm bg-p-surface-3 px-3 py-2 text-sm leading-6 text-p-text">{children}</p>
    </div>
  );
}

export function StreamingCursor() {
  return <span aria-hidden className="p-cursor" />;
}

export function AssistantMessage({ children, streaming, chips }: { children: ReactNode; streaming?: boolean; chips?: ReactNode }) {
  return (
    <div className="flex gap-3">
      <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md bg-p-accent-soft text-p-accent-text">
        <Sparkles size={13} strokeWidth={1.75} aria-hidden />
      </span>
      <div className="min-w-0 flex-1 space-y-2.5">
        <div className="space-y-2 text-sm leading-6 text-p-text">
          {children}{streaming && <StreamingCursor />}
        </div>
        {chips && <div className="flex flex-wrap gap-1.5">{chips}</div>}
      </div>
    </div>
  );
}

export function Thinking({ label = "Thinking" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3">
      <span className="flex size-6 items-center justify-center rounded-md bg-p-accent-soft text-p-accent-text">
        <Sparkles size={13} strokeWidth={1.75} aria-hidden />
      </span>
      <span className="p-shimmer-text text-sm">{label}…</span>
    </div>
  );
}

/* ---------- Agent activity timeline ---------- */
export type StepState = "done" | "running" | "waiting" | "queued" | "error";
export type Step = { id: string; label: string; detail?: string; state: StepState; kind: "plan" | "search" | "tool" | "approval" };

const STEP_ICON = { plan: Brain, search: Search, tool: Wrench, approval: ShieldCheck } as const;

function StepGlyph({ state, kind }: { state: StepState; kind: Step["kind"] }) {
  const Icon = STEP_ICON[kind];
  if (state === "running") return <Loader2 size={13} className="p-spin text-p-accent-text" aria-hidden />;
  if (state === "done") return <Check size={13} strokeWidth={2} className="text-p-ok" aria-hidden />;
  if (state === "error") return <Icon size={13} className="text-p-bad" aria-hidden />;
  if (state === "waiting") return <Icon size={13} className="text-p-warn" aria-hidden />;
  return <Circle size={11} className="text-p-muted" aria-hidden />;
}

export function ActivityTimeline({ steps }: { steps: Step[] }) {
  return (
    <ol aria-label="Agent activity" className="relative space-y-1 pl-1">
      {steps.map((s, i) => (
        <li key={s.id} className="relative flex items-start gap-3 pb-1">
          {i < steps.length - 1 && <span aria-hidden className="absolute left-[11px] top-6 h-[calc(100%-14px)] w-px bg-p-line-strong" />}
          <span className="z-10 mt-0.5 flex size-[22px] shrink-0 items-center justify-center rounded-full border border-p-line-strong bg-p-surface">
            <StepGlyph state={s.state} kind={s.kind} />
          </span>
          <div className="min-w-0 pt-0.5">
            <p className={`text-[13px] ${s.state === "queued" ? "text-p-muted" : "text-p-text"} ${s.state === "running" ? "p-shimmer-text" : ""}`}>{s.label}</p>
            {s.detail && <p className="font-mono text-[11px] text-p-muted">{s.detail}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}

/* ---------- Tool call card ---------- */
const STATUS: Record<"running" | "ok" | "error", { tone: Tone; text: string }> = {
  running: { tone: "accent", text: "Running" },
  ok: { tone: "ok", text: "Done" },
  error: { tone: "bad", text: "Failed" },
};

function Code({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[11px] font-medium uppercase tracking-wide text-p-muted">{label}</span>
        <button type="button" aria-label={`Copy ${label.toLowerCase()}`}
          onClick={() => { void navigator.clipboard?.writeText(value).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200); }, () => undefined); }}
          className="inline-flex items-center gap-1 rounded px-1 text-[11px] text-p-muted hover:text-p-text">
          {copied ? <Check size={11} aria-hidden /> : <Copy size={11} aria-hidden />}{copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="max-h-44 overflow-auto rounded-lg border border-p-line bg-p-bg p-2.5 font-mono text-xs leading-5 text-p-text">{value}</pre>
    </div>
  );
}

export function ToolCallCard({ name, app, logo, status, duration, input, output, defaultOpen = false, error }: {
  name: string; app: string; logo: ReactNode; status: "running" | "ok" | "error"; duration?: string;
  input?: string; output?: string; defaultOpen?: boolean; error?: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const st = STATUS[status];
  return (
    <div className={`rounded-lg border bg-p-surface ${status === "error" ? "border-p-bad/40" : "border-p-line"}`}>
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-p-surface-2">
        <LogoTile size={22}>{logo}</LogoTile>
        <span className="min-w-0 flex-1 truncate text-[13px]"><span className="text-p-muted">{app} · </span><span className="font-mono text-xs">{name}</span></span>
        {duration && <span className="font-mono text-[11px] text-p-muted">{duration}</span>}
        <PBadge tone={st.tone} dot>{st.text}</PBadge>
        <ChevronRight size={14} aria-hidden className={`text-p-muted transition-transform duration-150 ${open ? "rotate-90" : ""}`} />
      </button>
      {error && <p className="px-3 pb-2.5 text-[13px] text-p-bad">{error}</p>}
      {open && (input || output) && (
        <div className="space-y-3 border-t border-p-line p-2.5">
          {input && <Code label="Input" value={input} />}
          {output && <Code label="Output" value={output} />}
        </div>
      )}
    </div>
  );
}

/* ---------- Approval card ---------- */
export function ApprovalCard({ app, logo, action, risk, description, args, onDecide }: {
  app: string; logo: ReactNode; action: string; risk: "write" | "destructive"; description: string;
  args: Record<string, string>; onDecide?: (approve: boolean) => void;
}) {
  return (
    <section aria-label={`Approval needed: ${app} ${action}`}
      className={`rounded-xl border bg-p-surface p-3.5 ${risk === "destructive" ? "border-p-bad/40" : "border-p-warn/40"}`}>
      <div className="flex items-center gap-2.5">
        <LogoTile size={24}>{logo}</LogoTile>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[13px] font-medium">{app} · {action}</h3>
          <p className="text-xs text-p-muted">{description}</p>
        </div>
        <PBadge tone={risk === "destructive" ? "bad" : "warn"} dot>{risk === "destructive" ? "Destructive" : "Needs approval"}</PBadge>
      </div>
      <dl className="mt-3 divide-y divide-p-line overflow-hidden rounded-lg border border-p-line bg-p-bg font-mono text-xs">
        {Object.entries(args).map(([k, v]) => (
          <div key={k} className="grid grid-cols-[7rem_1fr] gap-3 px-2.5 py-1.5">
            <dt className="text-p-muted">{k}</dt><dd className="break-all">{v}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-3 flex items-center gap-2">
        <PButton icon={Check} kbd="↵" onClick={() => onDecide?.(true)}>Approve</PButton>
        <PButton variant="secondary" kbd="Esc" onClick={() => onDecide?.(false)}>Reject</PButton>
        <span className="ml-auto text-[11px] text-p-muted">Runs once. Nothing happens until you approve.</span>
      </div>
    </section>
  );
}

/* ---------- Composer + status bar ---------- */
export function Composer({ mode, modeLogo, value, onChange, busy }: {
  mode: string; modeLogo?: ReactNode; value: string; onChange: (v: string) => void; busy?: boolean;
}) {
  return (
    <Float className="p-2">
      <div className="mb-1.5 flex items-center gap-1.5 px-1">
        <span className="inline-flex h-6 items-center gap-1.5 rounded-md border border-p-line-strong bg-p-surface px-1.5 font-mono text-[11px]">
          {modeLogo}/{mode}
        </span>
        <span className="text-[11px] text-p-muted">Type <Kbd>/</Kbd> to switch mode</span>
      </div>
      <div className="flex items-end gap-2">
        <label htmlFor="pro-composer" className="sr-only">Message</label>
        <textarea id="pro-composer" rows={2} value={value} onChange={(e) => onChange(e.target.value)}
          placeholder="Ask anything, or / for modes…"
          className="min-h-[44px] flex-1 resize-none bg-transparent px-2 py-1.5 text-sm leading-6 text-p-text placeholder:text-p-muted focus:outline-none" />
        {busy ? (
          <PIconButton label="Stop generating" icon={Square} className="!bg-p-text !text-p-bg" />
        ) : (
          <PIconButton label="Send" icon={ArrowUp} disabled={!value.trim()} className="!bg-p-accent !text-p-accent-fg hover:!bg-p-accent-hover" />
        )}
      </div>
    </Float>
  );
}

export function StatusBar({ mode, model, memory }: { mode: string; model: string; memory: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-1 pt-2 text-[11px] text-p-muted">
      <span className="inline-flex items-center gap-1.5"><Sparkles size={11} aria-hidden />Mode <span className="font-mono text-p-text">/{mode}</span></span>
      <span className="inline-flex items-center gap-1.5"><Cpu size={11} aria-hidden />Model <span className="font-mono text-p-text">{model}</span></span>
      <span className="inline-flex items-center gap-1.5"><Brain size={11} aria-hidden />Memory <span className={memory ? "text-p-ok" : "text-p-muted"}>{memory ? "on" : "off"}</span></span>
      <span className="ml-auto hidden items-center gap-3 sm:inline-flex">
        <span><Kbd>↵</Kbd> send</span><span><Kbd>⇧↵</Kbd> new line</span><span><Kbd>⌘K</Kbd> commands</span>
      </span>
    </div>
  );
}
