"use client";

import { useState } from "react";
import type { Inline } from "@/lib/format";
import { displayText, parseMarkdown } from "@/lib/format";
import { CheckIcon, CopyIcon } from "@/components/ui/icons";

function renderInline(parts: Inline[]) {
  return parts.map((p, i) => {
    switch (p.t) {
      case "bold":
        return <strong key={i}>{p.v}</strong>;
      case "em":
        return <em key={i}>{p.v}</em>;
      case "code":
        return <code key={i} className="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-[0.85em]">{p.v}</code>;
      case "link":
        return (
          <a key={i} href={p.href} target="_blank" rel="noopener noreferrer"
            className="font-medium underline decoration-line-strong underline-offset-4 hover:decoration-foreground">{p.v}</a>
        );
      default:
        return <span key={i}>{p.v}</span>;
    }
  });
}

export function CopyButton({ text, label = "Copy", className = "" }: { text: string; label?: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable: the text stays selectable */
    }
  }
  return (
    <button type="button" onClick={copy} aria-label={copied ? "Copied" : label}
      className={`inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs text-muted transition-colors hover:bg-surface-2 hover:text-foreground ${className}`}>
      {copied ? <CheckIcon width={14} height={14} /> : <CopyIcon width={14} height={14} />}
      <span>{copied ? "Copied" : label}</span>
    </button>
  );
}

/** Formatted assistant message. Raw JSON is replaced by readable text (see displayText). */
export function Markdown({ text }: { text: string }) {
  const blocks = parseMarkdown(displayText(text));
  return (
    <div className="min-w-0 space-y-3 break-words text-[15px] leading-7">
      {blocks.map((b, i) => {
        switch (b.t) {
          case "h":
            return <p key={i} className={`font-semibold tracking-tight ${b.level === 1 ? "text-xl" : b.level === 2 ? "text-lg" : "text-base"}`}>{renderInline(b.inline)}</p>;
          case "ul":
            return <ul key={i} className="list-disc space-y-1 pl-6 marker:text-muted">{b.items.map((it, j) => <li key={j}>{renderInline(it)}</li>)}</ul>;
          case "ol":
            return <ol key={i} className="list-decimal space-y-1 pl-6 marker:text-muted">{b.items.map((it, j) => <li key={j}>{renderInline(it)}</li>)}</ol>;
          case "code":
            return (
              <div key={i} className="overflow-hidden rounded-xl border border-line bg-surface">
                <div className="flex items-center justify-between border-b border-line px-3 py-1">
                  <span className="font-mono text-xs text-muted">{b.lang ?? "code"}</span>
                  <CopyButton text={b.v} label="Copy code" />
                </div>
                <pre className="overflow-auto p-3 font-mono text-[13px] leading-6"><code>{b.v}</code></pre>
              </div>
            );
          case "table":
            return (
              <div key={i} className="overflow-x-auto rounded-xl border border-line">
                <table className="w-full border-collapse text-left text-sm">
                  <thead className="bg-surface">
                    <tr>{b.head.map((h, j) => <th key={j} scope="col" className="border-b border-line px-3 py-2 font-medium">{renderInline(h)}</th>)}</tr>
                  </thead>
                  <tbody>
                    {b.rows.map((r, j) => (
                      <tr key={j} className="border-b border-line last:border-0">
                        {r.map((c, k) => <td key={k} className="px-3 py-2 align-top">{renderInline(c)}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          default:
            return <p key={i}>{renderInline(b.inline)}</p>;
        }
      })}
    </div>
  );
}
