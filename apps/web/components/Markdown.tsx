import type { Inline } from "@/lib/format";
import { displayText, parseMarkdown } from "@/lib/format";

function renderInline(parts: Inline[]) {
  return parts.map((p, i) => {
    switch (p.t) {
      case "bold":
        return <strong key={i}>{p.v}</strong>;
      case "em":
        return <em key={i}>{p.v}</em>;
      case "code":
        return <code key={i} className="rounded bg-neutral-100 px-1 py-0.5 text-[0.85em] dark:bg-neutral-800">{p.v}</code>;
      case "link":
        return (
          <a key={i} href={p.href} target="_blank" rel="noopener noreferrer"
            className="font-medium text-blue-700 underline dark:text-blue-400">{p.v}</a>
        );
      default:
        return <span key={i}>{p.v}</span>;
    }
  });
}

/** Formatted assistant message. Raw JSON is replaced by readable text (see displayText). */
export function Markdown({ text }: { text: string }) {
  const blocks = parseMarkdown(displayText(text));
  return (
    <div className="max-w-[85%] space-y-2 break-words text-sm leading-relaxed">
      {blocks.map((b, i) => {
        switch (b.t) {
          case "h":
            return <p key={i} className="font-semibold">{renderInline(b.inline)}</p>;
          case "ul":
            return <ul key={i} className="list-disc space-y-1 pl-5">{b.items.map((it, j) => <li key={j}>{renderInline(it)}</li>)}</ul>;
          case "ol":
            return <ol key={i} className="list-decimal space-y-1 pl-5">{b.items.map((it, j) => <li key={j}>{renderInline(it)}</li>)}</ol>;
          case "code":
            return <pre key={i} className="overflow-auto rounded-md bg-neutral-100 p-2 text-xs dark:bg-neutral-800">{b.v}</pre>;
          default:
            return <p key={i}>{renderInline(b.inline)}</p>;
        }
      })}
    </div>
  );
}
