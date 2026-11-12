/** Tiny window-event bus so the sidebar (app shell) and the chat page stay in sync without shared props. */
export const CHAT_OPEN = "chat:open";       // detail: conversation id
export const CHAT_NEW = "chat:new";
export const CHAT_CHANGED = "chat:changed"; // the conversation list changed (new, renamed, deleted)
export const CHAT_DELETED = "chat:deleted"; // detail: id of a deleted conversation

export function emit(name: string, detail?: unknown): void {
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(name, { detail }));
}

export function on<T = unknown>(name: string, fn: (detail: T) => void): () => void {
  const handler = (e: Event) => fn((e as CustomEvent<T>).detail);
  window.addEventListener(name, handler);
  return () => window.removeEventListener(name, handler);
}
