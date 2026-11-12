import type { HTMLAttributes, ReactNode } from "react";

export function Card({ className = "", ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div {...rest} className={`glass rounded-2xl ${className}`} />;
}

export type BadgeTone = "neutral" | "success" | "warning" | "error";
const TONE: Record<BadgeTone, string> = {
  neutral: "border-line bg-surface text-muted",
  success: "border-ok/40 bg-ok/10 text-ok",
  warning: "border-warn/40 bg-warn/10 text-warn",
  error: "border-bad/40 bg-bad/10 text-bad",
};

export function Badge({ tone = "neutral", children, className = "" }: { tone?: BadgeTone; children: ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium ${TONE[tone]} ${className}`}>
      {tone !== "neutral" && <span aria-hidden className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden className={`skeleton rounded-lg ${className}`} />;
}

export function EmptyState({ title, children, action, icon }: { title: string; children?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="glass flex flex-col items-center gap-3 rounded-2xl border-dashed px-6 py-14 text-center">
      {icon && <div aria-hidden className="text-muted">{icon}</div>}
      <h2 className="text-base font-medium">{title}</h2>
      {children && <p className="max-w-md text-sm text-muted">{children}</p>}
      {action}
    </div>
  );
}

export function PageHeader({ title, description, actions, id }: { title: string; description?: ReactNode; actions?: ReactNode; id?: string }) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 id={id} className="text-gradient text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-sm text-muted">{description}</p>}
      </div>
      {actions}
    </div>
  );
}
