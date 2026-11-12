"use client";

import type { ChatMode } from "@/lib/modes";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { FlowIcon, SparkIcon } from "@/components/ui/icons";

export const SLASH_MENU_ID = "slash-menu";
export const optionId = (command: string) => `slash-option-${command}`;

export function ModeIcon({ mode, size = 16 }: { mode: ChatMode; size?: number }) {
  if (mode.kind === "connector" && mode.connector) return <BrandLogo id={mode.connector} name={mode.label} size={Math.round(size * 0.8)} />;
  return mode.kind === "workflow" ? <FlowIcon width={size} height={size} /> : <SparkIcon width={size} height={size} />;
}

/** The "/" autocomplete. Focus stays in the textarea; the active option is announced via aria-activedescendant. */
export function SlashMenu({
  modes, activeIndex, onPick, onHover,
}: {
  modes: ChatMode[];
  activeIndex: number;
  onPick: (m: ChatMode) => void;
  onHover: (i: number) => void;
}) {
  return (
    <ul id={SLASH_MENU_ID} role="listbox" aria-label="Chat modes"
      className="anim-pop absolute bottom-full left-0 right-0 z-10 mb-2 max-h-72 overflow-auto glass-strong rounded-2xl p-1.5">
      {modes.length === 0 && <li className="px-3 py-2 text-sm text-muted">No mode matches. Press Enter to send it as text.</li>}
      {modes.map((m, i) => (
        <li key={m.command} id={optionId(m.command)} role="option" aria-selected={i === activeIndex}
          onMouseEnter={() => onHover(i)}
          onMouseDown={(e) => { e.preventDefault(); onPick(m); }}
          className={`flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2 text-sm ${i === activeIndex ? "bg-surface-2" : ""}`}>
          <span className="flex size-6 shrink-0 items-center justify-center"><ModeIcon mode={m} /></span>
          <span className="font-mono font-medium">/{m.command}</span>
          <span className="truncate text-muted">{m.description}</span>
        </li>
      ))}
    </ul>
  );
}
