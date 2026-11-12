"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, IconButton } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/components/ui/theme";
import {
  BrainIcon, FlowIcon, GearIcon, LogoMark, MoonIcon, PencilIcon, PlayIcon, PlugIcon, PlusIcon,
  SearchIcon, SidebarIcon, SunIcon, TrashIcon,
} from "@/components/ui/icons";
import { chatApi, type Conversation } from "@/lib/chat";
import { CHAT_CHANGED, CHAT_DELETED, CHAT_NEW, CHAT_OPEN, emit, on } from "@/lib/chatBus";
import { groupByDate } from "@/lib/groupByDate";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

const NAV = [
  { href: "/connections", label: "Connections", Icon: PlugIcon },
  { href: "/workflows", label: "Workflows", Icon: FlowIcon },
  { href: "/runs", label: "Runs", Icon: PlayIcon },
  { href: "/memory", label: "Memory", Icon: BrainIcon },
  { href: "/settings", label: "Settings", Icon: GearIcon },
];

type Props = { collapsed: boolean; onToggleCollapsed: () => void; onNavigate?: () => void; mobile?: boolean };

function UserMenu({ collapsed }: { collapsed: boolean }) {
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    try {
      getSupabaseBrowserClient().auth.getSession().then(
        ({ data }) => alive && setEmail(data.session?.user?.email ?? null),
        () => undefined,
      );
    } catch { /* no session in isolated renders */ }
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);

  async function signOut() {
    await getSupabaseBrowserClient().auth.signOut();
    router.replace("/login");
    router.refresh();
  }

  const initial = (email ?? "?").charAt(0).toUpperCase();
  return (
    <div ref={ref} className="relative">
      <button type="button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        aria-label="User menu"
        className="flex w-full items-center gap-2.5 rounded-lg p-2 text-left hover:bg-surface-2">
        <span aria-hidden className="flex size-7 shrink-0 items-center justify-center rounded-full btn-gradient text-xs font-semibold">{initial}</span>
        {!collapsed && <span className="min-w-0 flex-1 truncate text-sm">{email ?? "Account"}</span>}
      </button>
      {open && (
        <div role="menu" aria-label="User menu"
          className="anim-pop absolute bottom-full left-0 z-30 mb-2 w-56 glass-strong rounded-2xl p-1">
          {email && <p className="truncate px-3 py-2 text-xs text-muted">{email}</p>}
          <Link role="menuitem" href="/settings" onClick={() => setOpen(false)}
            className="block rounded-lg px-3 py-2 text-sm hover:bg-surface-2">Settings</Link>
          <button type="button" role="menuitem" onClick={signOut}
            className="block w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-surface-2">Sign out</button>
        </div>
      )}
    </div>
  );
}

export function Sidebar({ collapsed, onToggleCollapsed, onNavigate, mobile }: Props) {
  const pathname = usePathname() ?? "";
  const router = useRouter();
  const { toast } = useToast();
  const { resolved, toggle } = useTheme();
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [query, setQuery] = useState("");
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

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? convs.filter((c) => (c.title || "Untitled").toLowerCase().includes(q)) : convs;
  }, [convs, query]);
  const groups = useMemo(() => groupByDate(filtered), [filtered]);

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

  const iconOnly = collapsed && !mobile;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className={`flex h-14 shrink-0 items-center ${iconOnly ? "justify-center" : "justify-between px-3"}`}>
        {!iconOnly && (
          <Link href="/chat" onClick={onNavigate} className="flex items-center gap-2 rounded-lg px-2 py-1 font-semibold tracking-tight">
            <LogoMark /> Connect
          </Link>
        )}
        {!mobile && (
          <IconButton label={collapsed ? "Expand sidebar" : "Collapse sidebar"} onClick={onToggleCollapsed}>
            <SidebarIcon />
          </IconButton>
        )}
      </div>

      <div className={`shrink-0 ${iconOnly ? "px-2" : "px-3"}`}>
        {iconOnly ? (
          <IconButton label="New chat" variant="primary" className="mx-auto size-10" onClick={newChat}><PlusIcon /></IconButton>
        ) : (
          <Button variant="secondary" className="w-full justify-start" onClick={newChat}><PlusIcon /> New chat</Button>
        )}
      </div>

      {!iconOnly && (
        <div className="relative mt-3 shrink-0 px-3">
          <SearchIcon className="pointer-events-none absolute left-5.5 top-1/2 -translate-y-1/2 text-muted" width={14} height={14} />
          <label htmlFor="chat-search" className="sr-only">Search chats</label>
          <Input id="chat-search" type="search" value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="Search chats" className="h-8 pl-8 text-xs" />
        </div>
      )}

      <nav aria-label="Chat history" className={`mt-3 min-h-0 flex-1 overflow-y-auto px-2 pb-2 ${iconOnly ? "hidden" : ""}`}>
        {loaded && groups.length === 0 && (
          <p className="px-2 py-3 text-xs text-muted">{query ? "No chats match your search." : "No chats yet. Start one above."}</p>
        )}
        {groups.map((g) => (
          <section key={g.label} aria-label={g.label} className="mb-3">
            <h3 className="px-2 pb-1 text-xs font-medium text-muted">{g.label}</h3>
            <ul>
              {g.items.map((c) => (
                <li key={c.id} className="group relative">
                  <button type="button" onClick={() => open(c.id)} aria-current={c.id === activeChat ? "true" : undefined}
                    className={`block w-full truncate rounded-lg py-1.5 pl-2 pr-14 text-left text-sm ${c.id === activeChat ? "bg-surface-2 font-medium" : "text-muted hover:bg-surface-2 hover:text-foreground"}`}>
                    {c.title || "Untitled"}
                  </button>
                  <span className="absolute right-1 top-1/2 flex -translate-y-1/2 gap-0.5 opacity-0 focus-within:opacity-100 group-hover:opacity-100">
                    <IconButton label={`Rename ${c.title || "Untitled"}`} className="size-6"
                      onClick={() => { setRenaming(c); setTitle(c.title || ""); }}><PencilIcon width={13} height={13} /></IconButton>
                    <IconButton label={`Delete ${c.title || "Untitled"}`} className="size-6"
                      onClick={() => setDeleting(c)}><TrashIcon width={13} height={13} /></IconButton>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </nav>
      {iconOnly && <div className="flex-1" />}

      <nav aria-label="Main" className={`shrink-0 space-y-0.5 border-t border-line p-2`}>
        {NAV.map(({ href, label, Icon }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link key={href} href={href} onClick={onNavigate} aria-current={active ? "page" : undefined}
              aria-label={iconOnly ? label : undefined} title={iconOnly ? label : undefined}
              className={`flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm ${iconOnly ? "justify-center" : ""} ${active ? "bg-surface-2 font-medium" : "text-muted hover:bg-surface-2 hover:text-foreground"}`}>
              <Icon /> {!iconOnly && label}
            </Link>
          );
        })}
      </nav>

      <div className="shrink-0 space-y-1 border-t border-line p-2">
        <button type="button" onClick={toggle} aria-label={resolved === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-sm text-muted hover:bg-surface-2 hover:text-foreground ${iconOnly ? "justify-center" : ""}`}>
          {resolved === "dark" ? <SunIcon /> : <MoonIcon />}
          {!iconOnly && (resolved === "dark" ? "Light mode" : "Dark mode")}
        </button>
        <UserMenu collapsed={iconOnly} />
      </div>

      <Modal open={renaming !== null} onClose={() => setRenaming(null)} title="Rename chat"
        footer={<>
          <Button variant="secondary" onClick={() => setRenaming(null)}>Cancel</Button>
          <Button onClick={saveRename} disabled={!title.trim()}>Save</Button>
        </>}>
        <form onSubmit={(e) => { e.preventDefault(); void saveRename(); }}>
          <label htmlFor="rename-title" className="mb-1.5 block text-sm font-medium">Title</label>
          <Input id="rename-title" value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} autoFocus />
        </form>
      </Modal>
      <Modal alert open={deleting !== null} onClose={() => setDeleting(null)} title="Delete this chat?"
        description="The conversation and its messages are removed. This cannot be undone."
        footer={<>
          <Button variant="secondary" onClick={() => setDeleting(null)}>Cancel</Button>
          <Button variant="danger" onClick={confirmDelete}>Delete chat</Button>
        </>}>
        <p className="text-sm">{deleting?.title || "Untitled"}</p>
      </Modal>
    </div>
  );
}
