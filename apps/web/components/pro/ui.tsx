"use client";

import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

/* ---------- Button: 28 / 32 / 36 px, flat accent fill with a faint top highlight ---------- */
type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const VARIANT: Record<Variant, string> = {
  primary:
    "bg-p-accent text-p-accent-fg shadow-[inset_0_1px_0_rgba(255,255,255,0.18)] hover:bg-p-accent-hover",
  secondary: "border border-p-line-strong bg-p-surface text-p-text hover:bg-p-surface-2",
  ghost: "text-p-muted hover:bg-p-surface-2 hover:text-p-text",
  danger: "border border-p-bad/40 text-p-bad hover:bg-p-bad/10",
};
const SIZE: Record<Size, string> = {
  sm: "h-7 gap-1.5 px-2.5 text-xs",
  md: "h-8 gap-2 px-3 text-[13px]",
  lg: "h-9 gap-2 px-4 text-sm",
};

export const PButton = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; icon?: LucideIcon; kbd?: string }
>(function PButton({ variant = "primary", size = "md", icon: Icon, kbd, className = "", children, type = "button", ...rest }, ref) {
  return (
    <button ref={ref} type={type} {...rest}
      className={`inline-flex shrink-0 items-center justify-center rounded-lg font-medium transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50 ${VARIANT[variant]} ${SIZE[size]} ${className}`}>
      {Icon && <Icon size={15} strokeWidth={1.75} aria-hidden />}
      {children}
      {kbd && <Kbd className={variant === "primary" ? "!border-white/25 !bg-white/15 !text-white" : ""}>{kbd}</Kbd>}
    </button>
  );
});

export const PIconButton = forwardRef<
  HTMLButtonElement,
  Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> & { label: string; icon: LucideIcon; active?: boolean }
>(function PIconButton({ label, icon: Icon, active, className = "", type = "button", ...rest }, ref) {
  return (
    <button ref={ref} type={type} aria-label={label} title={label} {...rest}
      className={`inline-flex size-8 shrink-0 items-center justify-center rounded-lg transition-colors duration-150 disabled:opacity-50 ${active ? "bg-p-accent-soft text-p-accent-text" : "text-p-muted hover:bg-p-surface-2 hover:text-p-text"} ${className}`}>
      <Icon size={16} strokeWidth={1.75} aria-hidden />
    </button>
  );
});

/* ---------- Inputs ---------- */
export const PInput = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { icon?: LucideIcon }>(
  function PInput({ icon: Icon, className = "", ...rest }, ref) {
    return (
      <span className="relative block">
        {Icon && <Icon size={15} strokeWidth={1.75} aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-p-muted" />}
        <input ref={ref} {...rest}
          className={`h-8 w-full rounded-lg border border-p-line-strong bg-p-surface px-2.5 text-[13px] text-p-text placeholder:text-p-muted transition-colors duration-150 hover:border-p-muted focus-visible:border-p-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-p-accent/30 aria-[invalid=true]:border-p-bad ${Icon ? "pl-8" : ""} ${className}`} />
      </span>
    );
  },
);

export function PLabel({ htmlFor, children, hint }: { htmlFor: string; children: ReactNode; hint?: string }) {
  return (
    <label htmlFor={htmlFor} className="mb-1.5 block text-xs font-medium text-p-text">
      {children}{hint && <span className="ml-1 font-normal text-p-muted">{hint}</span>}
    </label>
  );
}

/* ---------- Small pieces ---------- */
export function Kbd({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <kbd className={`inline-flex h-[18px] min-w-[18px] items-center justify-center rounded border border-p-line-strong bg-p-surface-2 px-1 font-mono text-[10px] font-medium text-p-muted ${className}`}>
      {children}
    </kbd>
  );
}

export type Tone = "neutral" | "accent" | "ok" | "warn" | "bad" | "info";
const TONE: Record<Tone, string> = {
  neutral: "border-p-line-strong text-p-muted",
  accent: "border-p-accent/30 bg-p-accent-soft text-p-accent-text",
  ok: "border-p-ok/30 bg-p-ok/10 text-p-ok",
  warn: "border-p-warn/30 bg-p-warn/10 text-p-warn",
  bad: "border-p-bad/30 bg-p-bad/10 text-p-bad",
  info: "border-p-info/30 bg-p-info/10 text-p-info",
};

export function PBadge({ tone = "neutral", dot, children }: { tone?: Tone; dot?: boolean; children: ReactNode }) {
  return (
    <span className={`inline-flex h-5 items-center gap-1.5 rounded-md border px-1.5 text-[11px] font-medium ${TONE[tone]}`}>
      {dot && <span aria-hidden className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

/** Tool / source chip shown under a response. */
export function Chip({ icon: Icon, children, href }: { icon?: LucideIcon; children: ReactNode; href?: string }) {
  const cls = "inline-flex h-6 items-center gap-1.5 rounded-md border border-p-line bg-p-surface px-2 text-xs text-p-muted transition-colors hover:border-p-line-strong hover:text-p-text";
  const inner = <>{Icon && <Icon size={12} strokeWidth={1.75} aria-hidden />}{children}</>;
  return href ? <a href={href} target="_blank" rel="noopener noreferrer" className={cls}>{inner}</a> : <span className={cls}>{inner}</span>;
}

/** Small tile holding an app mark (the mark itself is passed in, full colour). */
export function LogoTile({ children, size = 24 }: { children: ReactNode; size?: number }) {
  return (
    <span style={{ width: size, height: size }}
      className="inline-flex shrink-0 items-center justify-center rounded-md border border-black/5 bg-white shadow-[0_1px_1px_rgba(0,0,0,0.12)]">
      {children}
    </span>
  );
}

export function Surface({ className = "", children, ...rest }: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return <div {...rest} className={`rounded-xl border border-p-line bg-p-surface ${className}`}>{children}</div>;
}

/** A floating layer: modal, popover, palette, composer. The only place glass is used. */
export function Float({ className = "", children, ...rest }: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return <div {...rest} className={`p-float rounded-xl ${className}`}>{children}</div>;
}

export function PEmptyState({ icon: Icon, title, children, action }: { icon: LucideIcon; title: string; children: ReactNode; action: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-p-line-strong px-6 py-10 text-center">
      <span className="flex size-9 items-center justify-center rounded-lg border border-p-line bg-p-surface-2 text-p-muted">
        <Icon size={17} strokeWidth={1.5} aria-hidden />
      </span>
      <div>
        <h3 className="text-sm font-medium text-p-text">{title}</h3>
        <p className="mx-auto mt-1 max-w-xs text-[13px] text-p-muted">{children}</p>
      </div>
      {action}
    </div>
  );
}

export function PSkeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden className={`rounded-md bg-p-surface-3 ${className}`} style={{ animation: "p-pulse 1.4s ease-in-out infinite alternate" }} />;
}
