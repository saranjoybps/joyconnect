"use client";

import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { MoreHorizontal, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { Button, IconButton } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Popover } from "@/components/ui/kit";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { chatApi, type Conversation } from "@/lib/chat";
import { CHAT_CHANGED, CHAT_DELETED, CHAT_NEW, CHAT_OPEN, emit, on } from "@/lib/chatBus";
import { timeAgo } from "@/lib/connections";

/** The separate, collapsible right-hand "Chat history": search, title + one-line preview + time, rename/delete, New chat. */
export function HistoryPanel({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname() ?? "";
  const router = useRouter();
  const { toast } = useToast();
  const searchId = useId();
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [query, setQuery] = useState("");
  const [menu, setMenu] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<Conversation | null>(null);
  const [title, setTitle] = useState("");
  const [deleting, setDeleting] = useState<Conversation | null>(null);
  const [activeChat, setActiveChat] = useState<string | null>(null);

  const refresh = useCallback(() => {
    chatApi.conversations().then((c) => { setConvs(c); setLoaded(true); }, () => setLoaded(true));
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => on(CHAT_CHANGED, refresh), [refresh]);
  useEffect(() => on<string>(CHAT_OPEN, setActiveChat), []);
  useEffect(() => on(CHAT_NEW, () => setActiveChat(null)), []);
  useEffect(() => {
    const read = () => setActiveChat(new URLSearchParams(window.location.search).get("c"));
    read();
    window.addEventListener("popstate", read);
    return () => window.removeEventListener("popstate", read);
  }, [pathname]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? convs.filter((c) => `${c.title ?? "Untitled"} ${c.preview ?? ""}`.toLowerCase().includes(q)) : convs;
  }, [convs, query]);

  function newChat() {
    emit(CHAT_NEW);
    setActiveChat(null);
    if (!pathname.startsWith("/chat")) router.push("/chat");
    else window.history.replaceState(null, "", "/chat");
    onNavigate?.();
  }

  function open(id: string) {
    setActiveChat(id);
    if (pathname.startsWith("/chat")) {
      window.history.replaceState(null, "", `/chat?c=${id}`);
      emit(CHAT_OPEN, id);
    } else router.push(`/chat?c=${id}`);
    onNavigate?.();
  }

  async function saveRename() {
    if (!renaming || !title.trim()) return;
    const target = renaming;
    try {
      const r = await chatApi.rename(target.id, title.trim());
      setConvs((l) => l.map((c) => (c.id === target.id ? { ...c, title: r.title } : c)));
      emit(CHAT_CHANGED);
      setRenaming(null);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  async function confirmDelete() {
    if (!deleting) return;
    const target = deleting;
    try {
      await chatApi.remove(target.id);
      setConvs((l) => l.filter((c) => c.id !== target.id));
      emit(CHAT_DELETED, target.id);
      if (activeChat === target.id) setActiveChat(null);
      setDeleting(null);
      toast("Chat deleted", "success");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  return (
    <section aria-label="Chat history" className="flex h-full w-72 flex-col rounded-2xl border border-m-line bg-m-panel shadow-[var(--m-shadow)]">
      <div className="px-4 pb-3 pt-4">
        <h2 className="text-[15px] font-semibold tracking-tight">Chat history</h2>
        <div className="relative mt-3">
          <Search size={14} strokeWidth={1.75} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-m-muted" />
          <label htmlFor={searchId} className="sr-only">Search chats</label>
          <Input id={searchId} type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search…"
            className="rounded-full bg-m-window pl-8" />
        </div>
      </div>

      <ul className="min-h-0 flex-1 divide-y divide-m-line overflow-y-auto px-2">
        {loaded && shown.length === 0 && (
          <li className="px-2 py-6 text-center text-[13px] text-m-muted">{query ? "No chats match your search." : "No chats yet. Start one below."}</li>
        )}
        {shown.map((c) => {
          const name = c.title || "Untitled";
          return (
            <li key={c.id} className="group relative">
              <button type="button" onClick={() => open(c.id)} aria-current={c.id === activeChat ? "true" : undefined}
                className={`block w-full rounded-xl px-2.5 py-3 pr-9 text-left transition-colors duration-150 hover:bg-m-soft ${c.id === activeChat ? "bg-m-soft" : ""}`}>
                <span className="block truncate text-[13px] font-medium">{name}</span>
                {c.preview && <span className="mt-0.5 block truncate text-xs text-m-muted">{c.preview}</span>}
                <span className="mt-1.5 block text-right text-[11px] text-m-muted">{timeAgo(c.created_at)}</span>
              </button>
              <div className="absolute right-1 top-2">
                <IconButton label={`Options for ${name}`} className="size-6 opacity-0 focus-visible:opacity-100 group-hover:opacity-100 aria-expanded:opacity-100"
                  aria-haspopup="menu" aria-expanded={menu === c.id} onClick={() => setMenu(menu === c.id ? null : c.id)}>
                  <MoreHorizontal size={15} strokeWidth={1.75} aria-hidden />
                </IconButton>
                <Popover open={menu === c.id} onClose={() => setMenu(null)} label={`${name} menu`} className="right-0 top-8 w-36">
                  <button type="button" onClick={() => { setMenu(null); setRenaming(c); setTitle(c.title || ""); }}
                    className="flex h-8 w-full items-center gap-2 rounded-lg px-2.5 text-[13px] hover:bg-m-soft"><Pencil size={13} aria-hidden />Rename</button>
                  <button type="button" onClick={() => { setMenu(null); setDeleting(c); }}
                    className="flex h-8 w-full items-center gap-2 rounded-lg px-2.5 text-[13px] text-m-bad hover:bg-m-bad/10"><Trash2 size={13} aria-hidden />Delete</button>
                </Popover>
              </div>
            </li>
          );
        })}
      </ul>

      <div className="p-3">
        <Button size="lg" className="w-full" onClick={newChat}><Plus size={15} strokeWidth={1.75} aria-hidden />Create new chat</Button>
      </div>

      <Modal open={renaming !== null} onClose={() => setRenaming(null)} title="Rename chat"
        footer={<>
          <Button variant="secondary" onClick={() => setRenaming(null)}>Cancel</Button>
          <Button onClick={saveRename} disabled={!title.trim()}>Save</Button>
        </>}>
        <form onSubmit={(e) => { e.preventDefault(); void saveRename(); }}>
          <label htmlFor="rename-title" className="mb-1.5 block text-[13px] font-medium">Title</label>
          <Input id="rename-title" value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} autoFocus />
        </form>
      </Modal>
      <Modal alert open={deleting !== null} onClose={() => setDeleting(null)} title="Delete this chat?"
        description="The conversation and its messages are removed. This cannot be undone."
        footer={<>
          <Button variant="secondary" onClick={() => setDeleting(null)}>Cancel</Button>
          <Button variant="danger" onClick={confirmDelete}>Delete chat</Button>
        </>}>
        <p className="text-[13px]">{deleting?.title || "Untitled"}</p>
      </Modal>
    </section>
  );
}
