"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

type Props = {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  size?: "md" | "lg";
  /** Destructive confirmations use role=alertdialog so assistive tech announces them as urgent. */
  alert?: boolean;
};

/** Accessible dialog: focus moves in, Tab is trapped, Esc and backdrop close, focus returns on close. */
export function Modal({ open, onClose, title, description, children, footer, size = "md", alert = false }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descId = useId();
  const closeRef = useRef(onClose);   // keep the latest handler without re-running the focus effect
  closeRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const node = ref.current;
    const first = node?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? node)?.focus();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") { e.stopPropagation(); closeRef.current(); return; }
      if (e.key !== "Tab" || !node) return;
      const items = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) { e.preventDefault(); return; }
      const a = items[0], z = items[items.length - 1];
      if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
      else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      previous?.focus?.();
    };
  }, [open]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-6">
      <div aria-hidden className="absolute inset-0 bg-[#0a0f24]/45" onClick={onClose} />
      <div ref={ref} role={alert ? "alertdialog" : "dialog"} aria-modal="true" aria-labelledby={titleId} aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        className={`anim-pop relative flex max-h-[92dvh] w-full flex-col glass-strong rounded-t-2xl sm:rounded-2xl ${size === "lg" ? "sm:max-w-2xl" : "sm:max-w-lg"}`}>
        <div className="border-b border-line px-6 py-4">
          <h2 id={titleId} className="text-base font-semibold">{title}</h2>
          {description && <p id={descId} className="mt-1 text-sm text-muted">{description}</p>}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">{children}</div>
        {footer && <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-6 py-4">{footer}</div>}
      </div>
    </div>
  );
}
