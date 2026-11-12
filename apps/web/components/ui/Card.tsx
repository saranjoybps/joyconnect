import type { HTMLAttributes, ReactNode } from "react";

export function Card({ className = "", ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div {...rest} className={`rounded-2xl border border-m-line bg-m-panel shadow-[var(--m-shadow)] ${className}`} />;
}

export type BadgeTone = "neutral" | "success" | "warning" | "error";
const TONE: Record<BadgeTone, string> = {
  neutral: "text-m-muted", success: "text-m-ok", warning: "text-m-warn", error: "text-m-bad",
};

/** Status as a dot plus quiet text, never a filled badge. */
export function Badge({ tone = "neutral", children, className = "" }: { tone?: BadgeTone; children: ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${TONE[tone]} ${className}`}>
      <span aria-hidden className="size-1.5 rounded-full bg-current" />
      {children}
    </span>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden className={`skeleton rounded-lg ${className}`} />;
}

export function EmptyState({ title, children, action, icon }: { title: string; children?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-m-line-strong px-6 py-14 text-center">
      {icon && <div aria-hidden className="text-m-muted">{icon}</div>}
      <h2 className="text-base font-medium">{title}</h2>
      {children && <p className="max-w-md text-[13px] text-m-muted">{children}</p>}
      {action}
    </div>
  );
}

export function PageHeader({ title, description, actions, id }: { title: string; description?: ReactNode; actions?: ReactNode; id?: string }) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 id={id} className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-[13px] text-m-muted">{description}</p>}
      </div>
      {actions}
    </div>
  );
}
