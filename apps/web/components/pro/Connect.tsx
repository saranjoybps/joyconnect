"use client";

import { useState, type ReactNode } from "react";
import { Check, Copy, ExternalLink, X } from "lucide-react";
import { Float, Kbd, LogoTile, PBadge, PButton, PInput, PLabel, Surface, type Tone } from "@/components/pro/ui";

/* ---------- Connector card ---------- */
export function ConnectorCard({ name, description, logo, status, tone, action, accounts }: {
  name: string; description: string; logo: ReactNode; status: string; tone: Tone; action: string; accounts?: string;
}) {
  return (
    <Surface className="flex flex-col gap-3 p-3.5 transition-colors duration-150 hover:border-p-line-strong">
      <div className="flex items-start justify-between gap-2">
        <LogoTile size={32}>{logo}</LogoTile>
        <PBadge tone={tone} dot>{status}</PBadge>
      </div>
      <div className="min-w-0 flex-1">
        <h3 className="text-sm font-medium">{name}</h3>
        <p className="mt-0.5 line-clamp-2 text-[13px] leading-5 text-p-muted">{description}</p>
        {accounts && <p className="mt-1.5 font-mono text-[11px] text-p-muted">{accounts}</p>}
      </div>
      <PButton variant={action === "Manage" ? "secondary" : "primary"} className="w-full" aria-label={`${action} ${name}`}>{action}</PButton>
    </Surface>
  );
}

/* ---------- Setup modal (floating glass) ---------- */
const STEPS = ["Create credentials", "Enter credentials", "Authorize", "Test"] as const;

export function SetupModalPreview({ logo, name, redirectUri }: { logo: ReactNode; name: string; redirectUri: string }) {
  const [step, setStep] = useState(1);
  const [copied, setCopied] = useState(false);
  return (
    <Float role="dialog" aria-label={`Set up ${name}`} className="mx-auto w-full max-w-xl overflow-hidden">
      <div className="flex items-center gap-3 border-b border-p-line px-4 py-3">
        <LogoTile size={28}>{logo}</LogoTile>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-medium">Connect {name}</h3>
          <p className="text-xs text-p-muted">Four short steps. Credentials stay on the server.</p>
        </div>
        <button type="button" aria-label="Close" className="rounded-md p-1 text-p-muted hover:bg-p-surface-2 hover:text-p-text"><X size={15} aria-hidden /></button>
      </div>

      <ol aria-label="Setup steps" className="flex gap-1 border-b border-p-line px-3 py-2">
        {STEPS.map((s, i) => {
          const n = i + 1, on = n === step, done = n < step;
          return (
            <li key={s} className="flex-1">
              <button type="button" aria-current={on ? "step" : undefined} onClick={() => setStep(n)}
                className={`flex h-8 w-full items-center justify-center gap-1.5 rounded-md text-xs transition-colors ${on ? "bg-p-accent-soft text-p-accent-text" : "text-p-muted hover:bg-p-surface-2 hover:text-p-text"}`}>
                <span className={`flex size-4 items-center justify-center rounded-full text-[10px] ${done ? "bg-p-ok text-p-bg" : "border border-current"}`}>
                  {done ? <Check size={10} strokeWidth={3} aria-hidden /> : n}
                </span>
                <span className="hidden sm:inline">{s}</span>
              </button>
            </li>
          );
        })}
      </ol>

      <div className="space-y-4 px-4 py-4">
        {step === 1 && (
          <>
            <ol className="list-decimal space-y-1.5 pl-4 text-[13px] leading-5">
              <li>Open the developer console and create an OAuth client.</li>
              <li>Choose “Web application”.</li>
              <li>Paste this redirect URI exactly:</li>
            </ol>
            <div className="flex items-center gap-2 rounded-lg border border-p-line bg-p-bg p-1.5 pl-2.5">
              <code className="min-w-0 flex-1 select-all break-all font-mono text-xs">{redirectUri}</code>
              <PButton variant="secondary" size="sm" icon={copied ? Check : Copy}
                onClick={() => { setCopied(true); setTimeout(() => setCopied(false), 1200); }}>{copied ? "Copied" : "Copy"}</PButton>
            </div>
            <PButton variant="secondary" icon={ExternalLink}>Open developer console</PButton>
          </>
        )}
        {step === 2 && (
          <div className="space-y-3">
            <div><PLabel htmlFor="m-id">Client ID</PLabel><PInput id="m-id" className="font-mono" placeholder="123456-abc.apps.googleusercontent.com" /></div>
            <div><PLabel htmlFor="m-secret" hint="(saved encrypted)">Client secret</PLabel><PInput id="m-secret" type="password" className="font-mono" placeholder="••••••••••••" /></div>
          </div>
        )}
        {step === 3 && (
          <div className="space-y-3">
            <p className="text-[13px] text-p-muted">You will be sent to {name} to approve access, then brought back here.</p>
            <ul className="flex flex-wrap gap-1.5">
              {["Sheets (read and write)", "Drive (metadata, read)", "Email address"].map((s) => (
                <li key={s} className="rounded-md border border-p-line px-2 py-0.5 text-xs text-p-muted">{s}</li>
              ))}
            </ul>
          </div>
        )}
        {step === 4 && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 rounded-lg border border-p-ok/30 bg-p-ok/10 px-3 py-2 text-[13px] text-p-ok">
              <Check size={14} aria-hidden /> Connection test passed · checked just now
            </div>
            <p className="font-mono text-xs text-p-muted">saran@example.com · 3 permissions granted</p>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between border-t border-p-line px-4 py-3">
        <span className="text-[11px] text-p-muted"><Kbd>Esc</Kbd> to close</span>
        <div className="flex gap-2">
          <PButton variant="ghost" disabled={step === 1} onClick={() => setStep(step - 1)}>Back</PButton>
          <PButton disabled={step === 4} onClick={() => setStep(step + 1)}>Continue</PButton>
        </div>
      </div>
    </Float>
  );
}

/* ---------- Run row (detail expanded) ---------- */
export function RunRow({ time, app, logo, tool, risk, status, took, input, output }: {
  time: string; app: string; logo: ReactNode; tool: string; risk: "read" | "write" | "destructive";
  status: "ok" | "error" | "pending"; took: string; input: string; output: string;
}) {
  const [open, setOpen] = useState(false);
  const tone: Tone = status === "ok" ? "ok" : status === "error" ? "bad" : "warn";
  return (
    <div className="border-b border-p-line last:border-0">
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        className="grid w-full grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 px-3 py-2.5 text-left transition-colors hover:bg-p-surface-2 sm:grid-cols-[9rem_10rem_1fr_5rem_5rem_4rem]">
        <span className="font-mono text-xs text-p-muted">{time}</span>
        <span className="flex items-center gap-2 text-[13px]"><LogoTile size={20}>{logo}</LogoTile>{app}</span>
        <span className="truncate font-mono text-xs">{tool}</span>
        <span className={`text-xs ${risk === "destructive" ? "text-p-bad" : risk === "write" ? "text-p-warn" : "text-p-muted"}`}>{risk}</span>
        <PBadge tone={tone} dot>{status}</PBadge>
        <span className="font-mono text-xs text-p-muted">{took}</span>
      </button>
      {open && (
        <div className="grid gap-3 border-t border-p-line bg-p-bg/60 p-3 md:grid-cols-2">
          {[["Input", input], ["Output", output]].map(([l, v]) => (
            <div key={l}>
              <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-p-muted">{l}</p>
              <pre className="max-h-40 overflow-auto rounded-lg border border-p-line bg-p-bg p-2.5 font-mono text-xs leading-5">{v}</pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
