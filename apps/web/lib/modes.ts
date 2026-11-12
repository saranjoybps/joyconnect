export type ChatMode = {
  /** Without the slash: "custom", "workflow", "google-docs", "trello". */
  command: string;
  kind: "custom" | "workflow" | "connector";
  label: string;
  description: string;
  aliases?: string[];
  connector?: string;
};

export const DEFAULT_MODE: ChatMode = {
  command: "custom",
  kind: "custom",
  label: "Custom",
  description: "Chat with all your connected apps (default).",
};

/** The text after the slash while the user is still typing the command (no space yet), else null. */
export function slashQuery(input: string): string | null {
  const m = /^\/([A-Za-z0-9_-]*)$/.exec(input);
  return m ? m[1].toLowerCase() : null;
}

/** Modes matching what was typed after "/": prefix matches first (command, alias, label), then substring matches. */
export function filterModes(modes: ChatMode[], query: string): ChatMode[] {
  const q = query.toLowerCase();
  if (!q) return modes;
  const names = (m: ChatMode) => [m.command, ...(m.aliases ?? []), m.label.toLowerCase().replace(/\s+/g, "-")];
  const prefix = modes.filter((m) => names(m).some((n) => n.startsWith(q)));
  const rest = modes.filter((m) => !prefix.includes(m) && names(m).some((n) => n.includes(q)));
  return [...prefix, ...rest];
}

/** A mode named exactly by `/word` (command or alias), e.g. when the user types "/trello" and presses Enter. */
export function exactMode(modes: ChatMode[], input: string): ChatMode | null {
  const q = slashQuery(input.trim());
  if (!q) return null;
  return modes.find((m) => m.command === q || (m.aliases ?? []).includes(q)) ?? null;
}

/** Keyboard handling for the slash menu: pure so it can be tested without a DOM. */
export function nextIndex(key: "ArrowDown" | "ArrowUp", index: number, count: number): number {
  if (count === 0) return 0;
  return key === "ArrowDown" ? (index + 1) % count : (index - 1 + count) % count;
}
