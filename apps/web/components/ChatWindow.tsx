"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ActionCard } from "@/components/ActionCard";
import { ApprovalPrompt } from "@/components/ApprovalPrompt";
import { CopyButton, Markdown } from "@/components/Markdown";
import { ModeIcon, SLASH_MENU_ID, SlashMenu, optionId } from "@/components/SlashMenu";
import { Button, IconButton } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Field";
import { BrainIcon, CloseIcon, PencilIcon, RefreshIcon, SendIcon, StopIcon } from "@/components/ui/icons";
import { applyEvent, chatApi, itemsFromDetail, type ChatItem } from "@/lib/chat";
import { CHAT_CHANGED, CHAT_DELETED, CHAT_NEW, CHAT_OPEN, emit, on } from "@/lib/chatBus";
import { connectionsApi } from "@/lib/connections";
import { DEFAULT_MODE, exactMode, filterModes, nextIndex, slashQuery, type ChatMode } from "@/lib/modes";
import type { SseEvent } from "@/lib/sse";

const SUGGESTIONS = [
  "List my Google Sheets",
  "Find my Notion pages about the roadmap",
  "Summarize my open Linear issues",
  "Draft a workflow that posts new Stripe payments to Slack",
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
    <section aria-label="Chat" className="relative flex h-[calc(100dvh-3.5rem)] flex-col md:h-dvh">
      <div role="log" aria-live="polite" aria-busy={busy} className="flex-1 overflow-y-auto">
        <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col gap-6 px-4 pb-6 pt-8 sm:px-6">
          {error && <p role="alert" className="text-sm text-bad">{error}</p>}

          {empty && (
            <div className="my-auto flex flex-col items-center gap-8 py-10 text-center anim-fade-up">
              {connected === false ? (
                <div className="max-w-md">
                  <h2 className="text-2xl font-semibold tracking-tight">Connect an app to get started</h2>
                  <p className="mt-2 text-sm text-muted">
                    The assistant works through the apps you connect, like Google Sheets, Slack or Notion.
                  </p>
                  <Link href="/connections"
                    className="mt-5 inline-flex h-10 items-center rounded-lg bg-accent px-5 text-sm font-medium text-accent-fg hover:opacity-85">
                    Go to Connections
                  </Link>
                </div>
              ) : (
                <>
                  <div>
                    <h2 className="text-gradient text-3xl font-semibold tracking-tight">What can I do for you?</h2>
                    <p className="mt-2 text-sm text-muted">Ask in plain language. Type / to pick an app or build a workflow.</p>
                  </div>
                  <ul aria-label="Suggested prompts" className="grid w-full gap-2 sm:grid-cols-2">
                    {SUGGESTIONS.map((s) => (
                      <li key={s}>
                        <button type="button" onClick={() => { setInput(s); inputRef.current?.focus(); }}
                          className="h-full w-full glass rounded-2xl px-4 py-3 text-left text-sm text-muted transition-colors hover:text-foreground hover:!border-line-strong">
                          {s}
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
                <ol key={`t${seg.entries[0].index}`} aria-label="Tool calls"
                  className="ml-1 space-y-2 border-l border-line">
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
                        <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-gradient-to-br from-indigo-600 to-violet-600 px-4 py-2.5 text-[15px] leading-7 text-white shadow-md">{item.text}</p>
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
                          className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs text-muted hover:bg-surface-2 hover:text-foreground">
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
                      className="inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-xs text-muted hover:border-line-strong hover:text-foreground">
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
                  <div key={index} role="alert" className="glass rounded-2xl !border-bad/50 p-3 text-sm">
                    <p className="text-bad">{item.text}</p>
                    {lastUserText && (
                      <Button size="sm" variant="secondary" className="mt-2" disabled={busy}
                        onClick={() => void send(undefined, lastUserText)}>Retry</Button>
                    )}
                  </div>
                );
            }
          })}

          {busy && !items.some((i) => i.kind === "tool" && i.status === "running") && items[items.length - 1]?.kind !== "assistant" && (
            <div aria-hidden className="flex gap-1.5 px-1">
              <span className="size-2 animate-pulse rounded-full bg-muted" />
              <span className="size-2 animate-pulse rounded-full bg-muted [animation-delay:150ms]" />
              <span className="size-2 animate-pulse rounded-full bg-muted [animation-delay:300ms]" />
            </div>
          )}
          <div ref={endRef} />
        </div>
      </div>

      <div className="border-t border-transparent bg-gradient-to-t from-[var(--background)] from-60% to-transparent px-4 pb-4 pt-2 sm:px-6">
        <form onSubmit={send} className="relative mx-auto w-full max-w-3xl">
          {menuOpen && <SlashMenu modes={matches} activeIndex={Math.min(menuIndex, Math.max(matches.length - 1, 0))} onPick={pickMode} onHover={setMenuIndex} />}
          <div className="mb-2 flex items-center gap-2 text-xs">
            <span data-testid="mode-chip" title={mode.description}
              className="inline-flex items-center gap-1.5 glass rounded-full py-1 pl-2.5 pr-1.5 font-mono font-medium">
              <ModeIcon mode={mode} size={14} />
              Mode: /{mode.command}
              {mode.kind !== "custom" && (
                <button type="button" aria-label="Back to /custom" onClick={() => setMode(DEFAULT_MODE)}
                  className="rounded-full p-0.5 text-muted hover:bg-surface-2 hover:text-foreground">
                  <CloseIcon width={12} height={12} />
                </button>
              )}
            </span>
            <span className="hidden text-muted sm:inline">Type / to switch mode</span>
          </div>
          <div className="flex items-end gap-2 glass-strong rounded-3xl p-2 transition-shadow focus-within:!border-accent focus-within:ring-2 focus-within:ring-accent/25">
            <label htmlFor="chat-input" className="sr-only">Message</label>
            <textarea ref={inputRef} id="chat-input" rows={1} value={input}
              onChange={(e) => { setInput(e.target.value); setMenuClosed(false); setMenuIndex(0); }} onKeyDown={onKeyDown}
              role="combobox" aria-autocomplete="list" aria-expanded={menuOpen} aria-controls={SLASH_MENU_ID}
              aria-activedescendant={menuOpen && matches.length ? optionId(matches[Math.min(menuIndex, matches.length - 1)].command) : undefined}
              placeholder={hasPending ? "Approve or reject the pending action first" : "Ask the assistant to do something…"}
              disabled={busy || hasPending}
              className="max-h-[200px] min-h-11 min-w-0 flex-1 resize-none bg-transparent px-3 py-2.5 text-[15px] leading-6 placeholder:text-muted focus:outline-none disabled:opacity-60" />
            {busy ? (
              <IconButton label="Stop generating" variant="primary" className="size-10 rounded-xl"
                onClick={() => abortRef.current?.abort()}>
                <StopIcon width={16} height={16} />
              </IconButton>
            ) : (
              <IconButton type="submit" label="Send" variant="primary" className="size-10 rounded-xl"
                disabled={hasPending || !input.trim()}>
                <SendIcon width={18} height={18} />
              </IconButton>
            )}
          </div>
          <p className="mt-2 text-center text-xs text-muted">Enter to send · Shift+Enter for a new line</p>
        </form>
      </div>
    </section>
  );
}
