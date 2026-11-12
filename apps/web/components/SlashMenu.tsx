"use client";

import type { ChatMode } from "@/lib/modes";

export const SLASH_MENU_ID = "slash-menu";
export const optionId = (command: string) => `slash-option-${command}`;

/** The "/" autocomplete. Focus stays in the textarea; the active option is announced via aria-activedescendant. */
export function SlashMenu({
  modes,
  activeIndex,
  onPick,
  onHover,
}: {
  modes: ChatMode[];
  activeIndex: number;
  onPick: (m: ChatMode) => void;
  onHover: (i: number) => void;
}) {
  return (
    <ul
      id={SLASH_MENU_ID}
      role="listbox"
      aria-label="Chat modes"
      className="absolute bottom-full left-3 right-3 z-10 mb-1 max-h-64 overflow-auto rounded-lg border border-neutral-200 bg-white p-1 shadow-lg dark:border-neutral-700 dark:bg-neutral-900"
    >
      {modes.length === 0 && <li className="px-3 py-2 text-sm text-neutral-600">No mode matches. Press Enter to send it as text.</li>}
      {modes.map((m, i) => (
        <li
          key={m.command}
          id={optionId(m.command)}
          role="option"
          aria-selected={i === activeIndex}
          onMouseEnter={() => onHover(i)}
          onMouseDown={(e) => {
            e.preventDefault(); // keep focus in the input
            onPick(m);
          }}
          className={`flex cursor-pointer items-baseline gap-2 rounded-md px-3 py-1.5 text-sm ${i === activeIndex ? "bg-neutral-100 dark:bg-neutral-800" : ""}`}
        >
          <span className="font-mono font-medium">/{m.command}</span>
          <span className="truncate text-neutral-600 dark:text-neutral-400">{m.description}</span>
        </li>
      ))}
    </ul>
  );
}
