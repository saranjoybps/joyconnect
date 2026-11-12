"use client";

import { forwardRef, useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

/* ---------- Pill buttons: primary = solid near-black (white in dark) ---------- */
type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANT: Record<Variant, string> = {
  primary: "bg-m-ink text-m-ink-fg hover:opacity-90",
  secondary: "border border-m-line-strong bg-m-panel text-m-text hover:bg-m-soft",
  ghost: "text-m-muted hover:bg-m-soft hover:text-m-text",
  danger: "border border-m-bad/40 bg-m-panel text-m-bad hover:bg-m-bad/10",
};
const SIZE = { sm: "h-7 px-3 text-xs gap-1.5", md: "h-9 px-4 text-[13px] gap-2", lg: "h-10 px-5 text-sm gap-2" };

export const MButton = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: keyof typeof SIZE; icon?: LucideIcon }
>(function MButton({ variant = "primary", size = "md", icon: Icon, className = "", children, type = "button", ...rest }, ref) {
  return (
    <button ref={ref} type={type} {...rest}
      className={`inline-flex shrink-0 items-center justify-center rounded-full font-medium transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50 ${VARIANT[variant]} ${SIZE[size]} ${className}`}>
      {Icon && <Icon size={15} strokeWidth={1.75} aria-hidden />}
      {children}
    </button>
  );
});

export const MIconButton = forwardRef<
  HTMLButtonElement,
  Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> & { label: string; icon: LucideIcon; tone?: "plain" | "ink"; size?: number }
>(function MIconButton({ label, icon: Icon, tone = "plain", size = 32, className = "", type = "button", ...rest }, ref) {
  return (
    <button ref={ref} type={type} aria-label={label} title={label} style={{ width: size, height: size }} {...rest}
      className={`inline-flex shrink-0 items-center justify-center rounded-full transition-colors duration-150 disabled:opacity-40 ${tone === "ink" ? "bg-m-ink text-m-ink-fg hover:opacity-90" : "text-m-muted hover:bg-m-soft hover:text-m-text"} ${className}`}>
      <Icon size={16} strokeWidth={1.75} aria-hidden />
    </button>
  );
});

/** Quiet pill chip (Attach, Mode, Options). */
export const MChip = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { icon?: LucideIcon; leading?: ReactNode }
>(function MChip({ icon: Icon, leading, className = "", children, type = "button", ...rest }, ref) {
  return (
    <button ref={ref} type={type} {...rest}
      className={`inline-flex h-8 items-center gap-1.5 rounded-full border border-m-line bg-m-panel px-3 text-xs text-m-muted transition-colors duration-150 hover:border-m-line-strong hover:text-m-text ${className}`}>
      {leading}{Icon && <Icon size={14} strokeWidth={1.75} aria-hidden />}{children}
    </button>
  );
});

export type Tone = "neutral" | "ok" | "warn" | "bad" | "info";
const TONE: Record<Tone, string> = {
  neutral: "text-m-muted", ok: "text-m-ok", warn: "text-m-warn", bad: "text-m-bad", info: "text-m-info",
};
/** Status as a dot plus quiet text: no filled badges. */
export function Status({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs ${TONE[tone]}`}>
      <span aria-hidden className="size-1.5 rounded-full bg-current" />{children}
    </span>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded border border-m-line-strong px-1 font-mono text-[10px] text-m-muted">{children}</kbd>;
}

export function LogoTile({ children, size = 28 }: { children: ReactNode; size?: number }) {
  return (
    <span style={{ width: size, height: size }}
      className="inline-flex shrink-0 items-center justify-center rounded-lg border border-black/[0.06] bg-white shadow-[0_1px_1px_rgba(0,0,0,0.06)]">
      {children}
    </span>
  );
}

/** Our own abstract glyph: three linked rings (apps joined into one flow). Soft accent, no glow. */
export function Glyph({ size = 56 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden>
      <defs>
        <linearGradient id="glyph-g" x1="8" y1="8" x2="56" y2="56">
          <stop stopColor="var(--m-accent)" stopOpacity="0.9" />
          <stop offset="1" stopColor="var(--m-text)" stopOpacity="0.55" />
        </linearGradient>
      </defs>
      <circle cx="24" cy="26" r="14" stroke="url(#glyph-g)" strokeWidth="2" />
      <circle cx="40" cy="26" r="14" stroke="url(#glyph-g)" strokeWidth="2" opacity="0.75" />
      <circle cx="32" cy="40" r="14" stroke="url(#glyph-g)" strokeWidth="2" opacity="0.55" />
      <circle cx="32" cy="31" r="2.5" fill="var(--m-accent)" />
    </svg>
  );
}

export function ThinkingDots() {
  return (
    <span role="status" aria-label="Thinking" className="inline-flex items-center gap-1">
      {[0, 1, 2].map((i) => <span key={i} aria-hidden style={{ animationDelay: `${i * 160}ms` }} className="m-dot size-1.5 rounded-full bg-m-muted" />)}
    </span>
  );
}

/** Small popover: closes on outside click and Esc. Plain surface with a soft shadow (no blur). */
export function Popover({ open, onClose, className = "", children, label }: {
  open: boolean; onClose: () => void; className?: string; children: ReactNode; label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) onClose(); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", down); document.removeEventListener("keydown", key); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div ref={ref} role="dialog" aria-label={label}
      className={`m-in absolute z-30 rounded-2xl border border-m-line bg-m-panel p-1.5 shadow-[var(--m-pop-shadow)] ${className}`}>
      {children}
    </div>
  );
}
