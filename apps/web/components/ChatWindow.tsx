"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ActionCard } from "@/components/ActionCard";
import { ApprovalPrompt } from "@/components/ApprovalPrompt";
import { CopyButton, Markdown } from "@/components/Markdown";
import { ModeIcon, SLASH_MENU_ID, SlashMenu, optionId } from "@/components/SlashMenu";
import { CalendarDays, Mic, Paperclip, Search, Sliders, Sparkles, Workflow } from "lucide-react";
import { Button, IconButton } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Field";
import { Chip, Glyph, Kbd, Popover, ThinkingDots } from "@/components/ui/kit";
import { BrainIcon, CloseIcon, PencilIcon, RefreshIcon, SendIcon, StopIcon } from "@/components/ui/icons";
import { applyEvent, chatApi, itemsFromDetail, type ChatItem } from "@/lib/chat";
import { CHAT_CHANGED, CHAT_DELETED, CHAT_MODE_IS, CHAT_NEW, CHAT_OPEN, CHAT_SET_MODE, emit, on } from "@/lib/chatBus";
import { connectionsApi } from "@/lib/connections";
import { memoryApi } from "@/lib/memory";
import { useUser } from "@/lib/useUser";
import { DEFAULT_MODE, exactMode, filterModes, nextIndex, slashQuery, type ChatMode } from "@/lib/modes";
import type { SseEvent } from "@/lib/sse";

const SUGGESTIONS = [
  { icon: Search, title: "Search my files", text: "Find a document, sheet or page across my connected apps.", prompt: "Search my files for the Q4 planning sheet" },
  { icon: Workflow, title: "Build a workflow", text: "Describe an automation and get a draft on the canvas.", prompt: "Build a workflow that posts new Stripe payments to Slack" },
  { icon: CalendarDays, title: "Check my calendar", text: "See what is coming up this week.", prompt: "What is on my calendar this week?" },
];

const isAbort = (e: unknown) => (e as { name?: string } | null)?.name === "AbortError";

type Segment =
  | { type: "item"; item: ChatItem; index: number }
  | { type: "tools"; entries: { item: Extract<ChatItem, { kind: "tool" }>; index: number }[] };

/** Consecutive tool calls become one timeline; everything else stays a single row. */
function segment(items: ChatItem[]): Segment[] {
  const out: Segment[] = [];
  items.forEach((item, index) => {
    if (item.kind === "tool") {
      const last = out[out.length - 1];
      if (last?.type === "tools") last.entries.push({ item, index });
      else out.push({ type: "tools", entries: [{ item, index }] });
    } else out.push({ type: "item", item, index });
  });
  return out;
}

export function ChatWindow() {
  const search = useSearchParams();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [items, setItems] = useState<ChatItem[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [modes, setModes] = useState<ChatMode[]>([DEFAULT_MODE]);
  const [mode, setMode] = useState<ChatMode>(DEFAULT_MODE);
  const [menuIndex, setMenuIndex] = useState(0);
  const [menuClosed, setMenuClosed] = useState(false);   // Esc closes the menu until the text changes
  const [editing, setEditing] = useState<{ index: number; text: string } | null>(null);
  const [menu, setMenu] = useState<"mode" | "options" | null>(null);
  const [memoryOn, setMemoryOn] = useState<boolean | null>(null);   // loaded when Options is first opened
  const user = useUser();
  const wantedMode = search?.get("mode") ?? null;
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const activeRef = useRef<string | null>(null);
  activeRef.current = activeId;
  const modesRef = useRef(modes);
  modesRef.current = modes;

  useEffect(() => {
    let alive = true;
    connectionsApi.list().then(
      (conns) => alive && setConnected(conns.some((c) => c.status === "active")),
      (e: Error) => alive && setError(e.message),
    );
    chatApi.modes().then((m) => alive && setModes(m), () => undefined);
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [items]);

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [input]);

  const openConversation = useCallback(async (id: string) => {
    setError(null);
    setEditing(null);
    setActiveId(id);
    try {
      const detail = await chatApi.conversation(id);
      setItems(itemsFromDetail(detail));
      setMode(modesRef.current.find((m) => m.command === detail.mode?.command) ?? DEFAULT_MODE);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setActiveId(null);
    setItems([]);
    setError(null);
    setEditing(null);
    setMode(DEFAULT_MODE);
    setInput("");
    inputRef.current?.focus();
  }, []);

  // The sidebar drives which conversation is open: a ?c= link, or an event when already on this page.
  const wanted = search?.get("c") ?? null;
  useEffect(() => {
    if (wanted && wanted !== activeRef.current) void openConversation(wanted);
  }, [wanted, openConversation]);
  useEffect(() => on<string>(CHAT_OPEN, (id) => { if (id !== activeRef.current) void openConversation(id); }), [openConversation]);
  useEffect(() => on(CHAT_NEW, reset), [reset]);

  // The sidebar's AI tools list drives the mode too: an event when already here, a ?mode= link from other pages.
  useEffect(() => on<string>(CHAT_SET_MODE, (cmd) => {
    const m = modesRef.current.find((x) => x.command === cmd);
    if (m) setMode(m);
  }), []);
  const appliedMode = useRef<string | null>(null);
  useEffect(() => {
    if (!wantedMode || appliedMode.current === wantedMode) return;
    const m = modes.find((x) => x.command === wantedMode);
    if (m) { appliedMode.current = wantedMode; setMode(m); }
  }, [wantedMode, modes]);
  useEffect(() => { emit(CHAT_MODE_IS, mode.command); }, [mode]);

  useEffect(() => {
    if (menu !== "options" || memoryOn !== null) return;
    memoryApi.list().then((r) => setMemoryOn(r.enabled), () => undefined);
  }, [menu, memoryOn]);
  async function toggleMemory(on: boolean) {
    setMemoryOn(on);
    try { await memoryApi.setEnabled(on); } catch (e) { setMemoryOn(!on); setError((e as Error).message); }
  }
  useEffect(() => on<string>(CHAT_DELETED, (id) => { if (id === activeRef.current) reset(); }), [reset]);

  async function consume(stream: AsyncGenerator<SseEvent>) {
    for await (const ev of stream) {
      if (ev.event === "mode") {
        const cmd = (ev.data as { command?: string })?.command;
        setMode((cur) => modes.find((m) => m.command === cmd) ?? (cmd === cur.command ? cur : DEFAULT_MODE));
      } else if (ev.event === "done") {
        const id = (ev.data as { conversation_id?: string })?.conversation_id;
        if (id && id !== activeRef.current) {
          setActiveId(id);
          activeRef.current = id;
          if (typeof window !== "undefined") window.history.replaceState(null, "", `/chat?c=${id}`);
        }
        emit(CHAT_CHANGED);
      } else {
        setItems((prev) => applyEvent(prev, ev));
      }
    }
  }

  /** Runs one streamed turn with a Stop button; a stop leaves what already arrived and marks running tools stopped. */
  async function run(start: (signal: AbortSignal) => AsyncGenerator<SseEvent>) {
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    try {
      await consume(start(controller.signal));
    } catch (err) {
      if (isAbort(err)) {
        setItems((prev) => prev.map((i) => (i.kind === "tool" && i.status === "running"
          ? { ...i, status: "error" as const, summary: "Stopped" } : i)));
      } else {
        setItems((prev) => [...prev, { kind: "error", text: (err as Error).message }]);
      }
    } finally {
      abortRef.current = null;
      setBusy(false);
    }
  }

  async function send(e?: FormEvent, override?: string) {
    e?.preventDefault();
    const text = (override ?? input).trim();
    if (!text || busy) return;
    const named = override === undefined ? exactMode(modes, text) : null;
    if (named) {            // "/trello" on its own only switches the mode
      pickMode(named);
      return;
    }
    if (override === undefined) setInput("");
    setError(null);
    setItems((prev) => [...prev, { kind: "user", text }]);
    await run((signal) => chatApi.send(text, activeRef.current, mode.command, signal));
  }

  /** Cut the conversation back to just before the n-th user message (server and screen), then send `text`. */
  async function resendFrom(index: number, text: string) {
    if (busy || !activeRef.current) return;
    const userIndex = items.slice(0, index).filter((i) => i.kind === "user").length;
    try {
      await chatApi.rewind(activeRef.current, userIndex);
    } catch (e) {
      setError((e as Error).message);
      return;
    }
    setEditing(null);
    setItems((prev) => prev.slice(0, index));
    await send(undefined, text);
  }

  async function decide(approvalId: string, approve: boolean) {
    const mark = (state: "submitting" | "approved" | "rejected" | "pending") =>
      setItems((prev) => prev.map((i) =>
        i.kind === "approval" && i.approval.approval_id === approvalId ? { ...i, state } : i));
    mark("submitting");
    try {
      mark(approve ? "approved" : "rejected");
      await run((signal) => chatApi.decide(approvalId, approve, signal));
    } catch (err) {
      mark("pending");
      setItems((prev) => [...prev, { kind: "error", text: (err as Error).message }]);
    }
  }

  const query = slashQuery(input);
  const menuOpen = query !== null && !menuClosed && !busy;
  const matches = menuOpen ? filterModes(modes, query) : [];

  function pickMode(m: ChatMode) {
    setMode(m);
    setInput("");
    setMenuIndex(0);
    setMenuClosed(false);
    inputRef.current?.focus();
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (menuOpen) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        setMenuIndex((i) => nextIndex(e.key as "ArrowDown" | "ArrowUp", i, matches.length));
        return;
      }
      if ((e.key === "Enter" || e.key === "Tab") && !e.shiftKey && matches.length > 0) {
        e.preventDefault();
        pickMode(matches[Math.min(menuIndex, matches.length - 1)]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setMenuClosed(true);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send();
    }
  }

  const lastUserText = [...items].reverse().find((i) => i.kind === "user")?.text;
  const lastUserIndex = items.map((i) => i.kind).lastIndexOf("user");
  const lastAssistantIndex = items.map((i) => i.kind).lastIndexOf("assistant");
  const hasPending = items.some((i) => i.kind === "approval" && (i.state === "pending" || i.state === "submitting"));
  const segments = useMemo(() => segment(items), [items]);
  const canRewind = !busy && !hasPending && activeId !== null;

  const empty = items.length === 0;

  return (
    <section aria-label="Chat" className="relative flex h-full min-h-0 flex-col">
      <div role="log" aria-live="polite" aria-busy={busy} className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex min-h-full w-full max-w-2xl flex-col gap-6 px-4 pb-6 pt-4 sm:px-6">
          {error && <p role="alert" className="text-[13px] text-bad">{error}</p>}

          {empty && (
            <div className="m-in my-auto flex flex-col items-center py-10 text-center">
              {connected === false ? (
                <div className="max-w-md">
                  <Glyph size={56} />
                  <h2 className="mt-6 text-2xl font-semibold tracking-tight">Connect an app to get started</h2>
                  <p className="mt-2 text-[13px] text-m-muted">
                    The assistant works through the apps you connect, like Google Sheets, Slack or Notion.
                  </p>
                  <Link href="/connections"
                    className="mt-5 inline-flex h-10 items-center rounded-full bg-m-ink px-5 text-[13px] font-medium text-m-ink-fg hover:opacity-90">
                    Go to Connections
                  </Link>
                </div>
              ) : (
                <>
                  <Glyph size={64} />
                  <h1 className="mt-8 text-[34px] font-semibold leading-tight tracking-tight">Welcome, {user.firstName}</h1>
                  <p className="mt-2 text-sm text-m-muted">How can I help you today?</p>
                  <ul aria-label="Suggested prompts" className="mt-10 grid w-full gap-3 sm:grid-cols-3">
                    {SUGGESTIONS.map(({ icon: Icon, title, text, prompt }) => (
                      <li key={title}>
                        <button type="button" onClick={() => { setInput(prompt); inputRef.current?.focus(); }}
                          className="h-full w-full rounded-2xl border border-m-line bg-m-panel p-4 text-left shadow-[var(--m-shadow)] transition-colors duration-150 hover:border-m-line-strong">
                          <span className="flex size-8 items-center justify-center rounded-lg bg-m-accent-soft text-m-accent"><Icon size={16} strokeWidth={1.75} aria-hidden /></span>
                          <span className="mt-4 block text-[13px] font-medium">{title}</span>
                          <span className="mt-1 block text-xs leading-5 text-m-muted">{text}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}

          {segments.map((seg) => {
            if (seg.type === "tools") {
              return (
                <ol key={`t${seg.entries[0].index}`} aria-label="Tool calls" className="space-y-2">
                  {seg.entries.map(({ item, index }) => (
                    <ActionCard key={item.id || index} label={item.label} status={item.status} summary={item.summary}
                      action={item.action} input={item.input} output={item.output} durationMs={item.duration_ms}
                      onRetry={lastUserText ? () => void send(undefined, lastUserText) : undefined} retryDisabled={busy} />
                  ))}
                </ol>
              );
            }
            const { item, index } = seg;
            switch (item.kind) {
              case "user":
                return (
                  <div key={index} className="group flex flex-col items-end gap-1">
                    {editing?.index === index ? (
                      <div className="w-full space-y-2">
                        <label htmlFor={`edit-${index}`} className="sr-only">Edit message</label>
                        <Textarea id={`edit-${index}`} rows={3} autoFocus value={editing.text}
                          onChange={(e) => setEditing({ index, text: e.target.value })} />
                        <div className="flex justify-end gap-2">
                          <Button variant="secondary" size="sm" onClick={() => setEditing(null)}>Cancel</Button>
                          <Button size="sm" disabled={!editing.text.trim() || !canRewind}
                            onClick={() => void resendFrom(index, editing.text)}>Save and resend</Button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl bg-m-soft px-4 py-2.5 text-sm leading-6">{item.text}</p>
                        <div className="flex gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                          <CopyButton text={item.text} label="Copy message" />
                          {canRewind && (
                            <IconButton label="Edit and resend" onClick={() => setEditing({ index, text: item.text })}>
                              <PencilIcon width={14} height={14} />
                            </IconButton>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                );
              case "assistant":
                return (
                  <div key={index} className="group">
                    <Markdown text={item.text} />
                    <div className="mt-1 flex gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                      <CopyButton text={item.text} label="Copy reply" />
                      {canRewind && index === lastAssistantIndex && lastUserIndex >= 0 && (
                        <button type="button" onClick={() => void resendFrom(lastUserIndex, (items[lastUserIndex] as { text: string }).text)}
                          className="inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-xs text-m-muted hover:bg-m-soft hover:text-m-text">
                          <RefreshIcon width={14} height={14} /> Regenerate
                        </button>
                      )}
                    </div>
                  </div>
                );
              case "memory":
                return (
                  <div key={index}>
                    <Link href="/memory"
                      className="inline-flex items-center gap-1.5 rounded-full border border-m-line px-2.5 py-1 text-xs text-m-muted hover:border-m-line-strong hover:text-m-text">
                      <BrainIcon width={13} height={13} /> Memory used
                      <span className="sr-only"> ({item.count} {item.count === 1 ? "item" : "items"}), open Memory</span>
                    </Link>
                  </div>
                );
              case "approval":
                return <ApprovalPrompt key={item.approval.approval_id} approval={item.approval} state={item.state}
                  onDecide={(approve) => decide(item.approval.approval_id, approve)} />;
              case "error":
                return (
                  <div key={index} role="alert" className="rounded-2xl border border-m-bad/40 bg-m-panel p-3 text-[13px]">
                    <p className="text-m-bad">{item.text}</p>
                    {lastUserText && (
                      <Button size="sm" variant="secondary" className="mt-2" disabled={busy}
                        onClick={() => void send(undefined, lastUserText)}>Retry</Button>
                    )}
                  </div>
                );
            }
          })}

          {busy && !items.some((i) => i.kind === "tool" && i.status === "running") && items[items.length - 1]?.kind !== "assistant" && (
            <ThinkingDots />
          )}
          <div ref={endRef} />
        </div>
      </div>

      <div className="px-4 pb-4 pt-2 sm:px-6">
        <form onSubmit={send} className="relative mx-auto w-full max-w-3xl">
          {menuOpen && <SlashMenu modes={matches} activeIndex={Math.min(menuIndex, Math.max(matches.length - 1, 0))} onPick={pickMode} onHover={setMenuIndex} />}
          <div className="rounded-2xl border border-m-line-strong bg-m-panel p-3 shadow-[var(--m-shadow)] transition-colors duration-150 focus-within:border-m-accent focus-within:ring-2 focus-within:ring-m-accent/20">
            <div className="flex items-start gap-2.5">
              <Sparkles size={16} strokeWidth={1.75} aria-hidden className="mt-2 shrink-0 text-m-muted" />
              <label htmlFor="chat-input" className="sr-only">Message</label>
              <textarea ref={inputRef} id="chat-input" rows={1} value={input}
                onChange={(e) => { setInput(e.target.value); setMenuClosed(false); setMenuIndex(0); }} onKeyDown={onKeyDown}
                role="combobox" aria-autocomplete="list" aria-expanded={menuOpen} aria-controls={SLASH_MENU_ID}
                aria-activedescendant={menuOpen && matches.length ? optionId(matches[Math.min(menuIndex, matches.length - 1)].command) : undefined}
                placeholder={hasPending ? "Approve or reject the pending action first" : "Ask anything, or type / for commands…"}
                disabled={busy || hasPending}
                className="max-h-[200px] min-h-[36px] min-w-0 flex-1 resize-none bg-transparent py-1.5 text-sm leading-6 placeholder:text-m-muted focus:outline-none disabled:opacity-60" />
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Chip icon={Paperclip} disabled title="Attachments are not available yet" aria-label="Attach (not available yet)">Attach</Chip>
              <span data-testid="mode-chip" title={mode.description} className="relative inline-flex">
                <Chip aria-haspopup="listbox" aria-expanded={menu === "mode"} onClick={() => setMenu(menu === "mode" ? null : "mode")}
                  leading={<ModeIcon mode={mode} size={12} />} className={mode.kind !== "custom" ? "pr-8" : ""}>
                  Mode <span className="font-mono text-m-text">/{mode.command}</span>
                </Chip>
                {mode.kind !== "custom" && (
                  <button type="button" aria-label="Back to /custom" onClick={() => setMode(DEFAULT_MODE)}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-full p-1 text-m-muted hover:bg-m-soft hover:text-m-text">
                    <CloseIcon width={11} height={11} />
                  </button>
                )}
                <Popover open={menu === "mode"} onClose={() => setMenu(null)} label="Choose a mode" className="bottom-full left-0 mb-2 w-72">
                  <ul role="listbox" aria-label="Modes" className="max-h-64 overflow-y-auto">
                    {modes.map((m) => (
                      <li key={m.command} role="option" aria-selected={m.command === mode.command}>
                        <button type="button" onClick={() => { setMode(m); setMenu(null); inputRef.current?.focus(); }}
                          className="flex h-9 w-full items-center gap-2.5 rounded-xl px-2.5 text-left text-[13px] hover:bg-m-soft">
                          <span className="flex w-6 justify-center"><ModeIcon mode={m} size={13} /></span>
                          <span className="font-mono text-xs">/{m.command}</span>
                          <span className="flex-1 truncate text-xs text-m-muted">{m.description}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </Popover>
              </span>
              <span className="relative inline-flex">
                <Chip icon={Sliders} aria-haspopup="dialog" aria-expanded={menu === "options"} onClick={() => setMenu(menu === "options" ? null : "options")}>Options</Chip>
                <Popover open={menu === "options"} onClose={() => setMenu(null)} label="Options" className="bottom-full left-0 mb-2 w-64 p-3">
                  <p className="text-xs font-medium">Model</p>
                  <p className="mt-1 text-[11px] text-m-muted">Set on the server (OPENAI_MODEL).</p>
                  <label className="mt-3 flex cursor-pointer items-center justify-between text-[13px]">
                    Memory
                    <input type="checkbox" role="switch" aria-label="Memory" checked={memoryOn ?? false} disabled={memoryOn === null}
                      onChange={(e) => void toggleMemory(e.target.checked)}
                      className="relative h-5 w-9 cursor-pointer appearance-none rounded-full bg-m-line-strong transition-colors checked:bg-m-ink disabled:opacity-50 after:absolute after:left-0.5 after:top-0.5 after:size-4 after:rounded-full after:bg-m-panel after:transition-transform checked:after:translate-x-4" />
                  </label>
                  <p className="mt-1 text-[11px] text-m-muted">Remember short facts between chats.</p>
                </Popover>
              </span>
              <span className="ml-auto" />
              <IconButton label="Voice input (not available yet)" disabled><Mic size={16} strokeWidth={1.75} aria-hidden /></IconButton>
              {busy ? (
                <IconButton label="Stop generating" variant="primary" className="size-9" onClick={() => abortRef.current?.abort()}>
                  <StopIcon width={14} height={14} />
                </IconButton>
              ) : (
                <IconButton type="submit" label="Send" variant="primary" className="size-9" disabled={hasPending || !input.trim()}>
                  <SendIcon width={16} height={16} />
                </IconButton>
              )}
            </div>
          </div>
          <p className="mt-2 flex items-center justify-center gap-3 text-[11px] text-m-muted">
            <span><Kbd>↵</Kbd> send</span><span><Kbd>⇧↵</Kbd> new line</span><span><Kbd>/</Kbd> commands</span>
          </p>
        </form>
      </div>
    </section>
  );
}
