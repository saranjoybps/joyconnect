"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

export type ToastKind = "success" | "error" | "info";
type Toast = { id: number; kind: ToastKind; text: string };
type Ctx = { toast: (text: string, kind?: ToastKind) => void };

const ToastCtx = createContext<Ctx>({ toast: () => {} });
export const useToast = () => useContext(ToastCtx);

const TONE: Record<ToastKind, string> = {
  success: "text-ok",
  error: "text-bad",
  info: "text-muted",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const next = useRef(1);

  const dismiss = useCallback((id: number) => setItems((l) => l.filter((t) => t.id !== id)), []);
  const toast = useCallback((text: string, kind: ToastKind = "info") => {
    const id = next.current++;
    setItems((l) => [...l.slice(-3), { id, kind, text }]);
    setTimeout(() => dismiss(id), 4500);
  }, [dismiss]);

  const value = useMemo(() => ({ toast }), [toast]);
  return (
    <ToastCtx.Provider value={value}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(22rem,calc(100vw-2rem))] flex-col gap-2">
        {items.map((t) => (
          <div key={t.id} role={t.kind === "error" ? "alert" : "status"}
            className="anim-fade-up pointer-events-auto flex items-start gap-3 rounded-xl border border-line bg-background p-3 text-sm shadow-lg">
            <span aria-hidden className={`mt-1.5 size-2 shrink-0 rounded-full bg-current ${TONE[t.kind]}`} />
            <span className="min-w-0 flex-1">{t.text}</span>
            <button type="button" aria-label="Dismiss notification" onClick={() => dismiss(t.id)}
              className="text-muted hover:text-foreground">×</button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
