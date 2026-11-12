"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ActionCard } from "@/components/ActionCard";
import { ApprovalPrompt } from "@/components/ApprovalPrompt";
import { Markdown } from "@/components/Markdown";
import { applyEvent, chatApi, itemsFromDetail, type ChatItem, type Conversation } from "@/lib/chat";
import { connectionsApi } from "@/lib/connections";
import type { SseEvent } from "@/lib/sse";

export function ChatWindow() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [items, setItems] = useState<ChatItem[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    Promise.all([chatApi.conversations(), connectionsApi.list()]).then(
      ([convs, conns]) => {
        if (!alive) return;
        setConversations(convs);
        setConnected(conns.some((c) => c.status === "active"));
      },
      (e: Error) => alive && setError(e.message),
    );
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [items]);

  async function openConversation(id: string) {
    if (busy) return;
    setError(null);
    setActiveId(id);
    try {
      setItems(itemsFromDetail(await chatApi.conversation(id)));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const [confirmId, setConfirmId] = useState<string | null>(null);

  async function deleteConversation(id: string) {
    if (busy) return;
    try {
      await chatApi.remove(id);
      setConversations((list) => list.filter((c) => c.id !== id));
      if (id === activeId) {
        setActiveId(null);
        setItems([]);
      }
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setConfirmId(null);
    }
  }

  function newChat() {
    if (busy) return;
    setActiveId(null);
    setItems([]);
    setError(null);
  }

  async function consume(stream: AsyncGenerator<SseEvent>) {
    for await (const ev of stream) {
      if (ev.event === "done") {
        const id = (ev.data as { conversation_id?: string })?.conversation_id;
        if (id && id !== activeId) {
          setActiveId(id);
          chatApi.conversations().then(setConversations, () => undefined);
        }
      } else {
        setItems((prev) => applyEvent(prev, ev));
      }
    }
  }

  async function send(e?: FormEvent, override?: string) {
    e?.preventDefault();
    const text = (override ?? input).trim();
    if (!text || busy) return;
    if (override === undefined) setInput("");
    setError(null);
    setBusy(true);
    setItems((prev) => [...prev, { kind: "user", text }]);
    try {
      await consume(chatApi.send(text, activeId));
    } catch (err) {
      setItems((prev) => [...prev, { kind: "error", text: (err as Error).message }]);
    } finally {
      setBusy(false);
    }
  }

  async function decide(approvalId: string, approve: boolean) {
    const mark = (state: "submitting" | "approved" | "rejected" | "pending") =>
      setItems((prev) => prev.map((i) =>
        i.kind === "approval" && i.approval.approval_id === approvalId ? { ...i, state } : i));
    mark("submitting");
    setBusy(true);
    try {
      const stream = chatApi.decide(approvalId, approve);
      mark(approve ? "approved" : "rejected");
      await consume(stream);
    } catch (err) {
      mark("pending");
      setItems((prev) => [...prev, { kind: "error", text: (err as Error).message }]);
    } finally {
      setBusy(false);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  const lastUserText = [...items].reverse().find((i) => i.kind === "user")?.text;

  const hasPending = items.some((i) => i.kind === "approval" && (i.state === "pending" || i.state === "submitting"));

  return (
    <div className="grid gap-4 md:grid-cols-[14rem_1fr]">
      <aside aria-label="Conversations" className="space-y-2">
        <button type="button" onClick={newChat} disabled={busy}
          className="w-full rounded-md border border-neutral-300 px-3 py-1.5 text-sm font-medium disabled:opacity-50 dark:border-neutral-700">
          New chat
        </button>
        <ul className="max-h-[30vh] space-y-1 overflow-auto md:max-h-[70vh]">
          {conversations.map((c) => (
            <li key={c.id} className="flex items-center gap-1">
              {confirmId === c.id ? (
                <div role="group" aria-label={`Delete ${c.title || "Untitled"}?`} className="flex w-full items-center gap-1 text-sm">
                  <span className="flex-1 truncate">Delete this chat?</span>
                  <button type="button" onClick={() => deleteConversation(c.id)} disabled={busy}
                    className="rounded-md bg-red-600 px-2 py-1 text-xs font-medium text-white disabled:opacity-50">Delete</button>
                  <button type="button" onClick={() => setConfirmId(null)}
                    className="rounded-md border border-neutral-300 px-2 py-1 text-xs dark:border-neutral-700">Cancel</button>
                </div>
              ) : (
                <>
                  <button type="button" onClick={() => openConversation(c.id)} aria-current={c.id === activeId ? "true" : undefined}
                    className={`min-w-0 flex-1 truncate rounded-md px-2 py-1.5 text-left text-sm ${c.id === activeId
                      ? "bg-neutral-100 font-medium dark:bg-neutral-800" : "hover:bg-neutral-50 dark:hover:bg-neutral-900"}`}>
                    {c.title || "Untitled"}
                  </button>
                  <button type="button" onClick={() => setConfirmId(c.id)} disabled={busy}
                    aria-label={`Delete conversation ${c.title || "Untitled"}`} title="Delete conversation"
                    className="shrink-0 rounded-md px-2 py-1 text-sm text-neutral-500 hover:bg-red-50 hover:text-red-700 disabled:opacity-50 dark:hover:bg-neutral-800">
                    &#x1F5D1;
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      </aside>

      <section aria-label="Chat" className="flex min-h-[70vh] flex-col rounded-xl border border-neutral-200 dark:border-neutral-800">
        <div role="log" aria-live="polite" aria-busy={busy} className="flex-1 space-y-3 overflow-auto p-4">
          {error && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{error}</p>}
          {items.length === 0 && connected === false && (
            <div className="mx-auto max-w-md py-12 text-center">
              <h2 className="text-lg font-semibold">Connect an app to get started</h2>
              <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
                The assistant works through the apps you connect, like Google Sheets, Slack or Notion.
              </p>
              <Link href="/connections" className="mt-4 inline-block rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white dark:bg-white dark:text-neutral-900">
                Go to Connections
              </Link>
            </div>
          )}
          {items.length === 0 && connected && (
            <p className="py-12 text-center text-sm text-neutral-500">
              Try “add a row with Ada, ada@example.com to my sheet &lt;link&gt;” or “find my Notion pages about the roadmap”.
            </p>
          )}
          {items.map((item, idx) => {
            switch (item.kind) {
              case "user":
                return <p key={idx} className="ml-auto w-fit max-w-[85%] whitespace-pre-wrap rounded-2xl bg-neutral-900 px-3 py-2 text-white dark:bg-neutral-100 dark:text-neutral-900">{item.text}</p>;
              case "assistant":
                return <Markdown key={idx} text={item.text} />;
              case "tool":
                return <ActionCard key={idx} label={item.label} status={item.status} summary={item.summary} action={item.action}
                  onRetry={lastUserText ? () => void send(undefined, lastUserText) : undefined} retryDisabled={busy} />;
              case "approval":
                return <ApprovalPrompt key={item.approval.approval_id} approval={item.approval} state={item.state}
                  onDecide={(approve) => decide(item.approval.approval_id, approve)} />;
              case "error":
                return <p key={idx} role="alert" className="text-sm text-red-700 dark:text-red-400">{item.text}</p>;
            }
          })}
          <div ref={endRef} />
        </div>
        <form onSubmit={send} className="flex gap-2 border-t border-neutral-200 p-3 dark:border-neutral-800">
          <label htmlFor="chat-input" className="sr-only">Message</label>
          <textarea id="chat-input" rows={2} value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={onKeyDown}
            placeholder={hasPending ? "Approve or reject the pending action first" : "Ask the assistant to do something…"}
            disabled={busy || hasPending}
            className="flex-1 resize-none rounded-md border border-neutral-300 bg-transparent px-3 py-2 text-sm disabled:opacity-60 dark:border-neutral-700" />
          <button type="submit" disabled={busy || hasPending || !input.trim()}
            className="self-end rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-neutral-900">
            Send
          </button>
        </form>
      </section>
    </div>
  );
}
