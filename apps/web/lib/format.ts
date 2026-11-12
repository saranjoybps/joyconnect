/** Pure formatting helpers for assistant messages: a tiny safe Markdown parser and the raw-JSON fallback. */

export type Inline =
  | { t: "text"; v: string }
  | { t: "bold"; v: string }
  | { t: "em"; v: string }
  | { t: "code"; v: string }
  | { t: "link"; v: string; href: string };

export type Block =
  | { t: "p"; inline: Inline[] }
  | { t: "h"; level: 1 | 2 | 3; inline: Inline[] }
  | { t: "ul" | "ol"; items: Inline[][] }
  | { t: "code"; v: string; lang?: string }
  | { t: "table"; head: Inline[][]; rows: Inline[][][] };

const HTTP = /^https?:\/\/[^\s<>"']+$/i;
const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]+\]\([^)\s]+\)|https?:\/\/[^\s<>"')\]]+|\*[^*\n]+\*)/g;

export function parseInline(src: string): Inline[] {
  const out: Inline[] = [];
  let last = 0;
  for (const m of src.matchAll(INLINE)) {
    const tok = m[0];
    if (m.index > last) out.push({ t: "text", v: src.slice(last, m.index) });
    last = m.index + tok.length;
    if (tok.startsWith("**")) out.push({ t: "bold", v: tok.slice(2, -2) });
    else if (tok.startsWith("`")) out.push({ t: "code", v: tok.slice(1, -1) });
    else if (tok.startsWith("[")) {
      const [, label, href] = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(tok)!;
      // Only http(s) links become anchors; anything else (javascript:, data:) stays visible text.
      out.push(HTTP.test(href) ? { t: "link", v: label, href } : { t: "text", v: tok });
    } else if (tok.startsWith("http")) out.push({ t: "link", v: tok, href: tok });
    else out.push({ t: "em", v: tok.slice(1, -1) });
  }
  if (last < src.length) out.push({ t: "text", v: src.slice(last) });
  return out;
}

const isRow = (l: string) => l.includes("|") && l.trim() !== "";
const isSeparator = (l: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l) && l.includes("|");
const cells = (l: string) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

export function parseMarkdown(src: string): Block[] {
  const blocks: Block[] = [];
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  let para: string[] = [];
  let list: { t: "ul" | "ol"; items: Inline[][] } | null = null;
  const flush = () => {
    if (para.length) blocks.push({ t: "p", inline: parseInline(para.join(" ")) });
    para = [];
    if (list) blocks.push(list);
    list = null;
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.trim().startsWith("```")) {
      flush();
      const code: string[] = [];
      const lang = line.trim().slice(3).trim().split(/\s+/)[0];
      for (i++; i < lines.length && !lines[i].trim().startsWith("```"); i++) code.push(lines[i]);
      blocks.push(lang ? { t: "code", v: code.join("\n"), lang } : { t: "code", v: code.join("\n") });
      continue;
    }
    // GitHub-style table: a header row, a separator row of dashes, then body rows.
    if (isRow(line) && i + 1 < lines.length && isSeparator(lines[i + 1])) {
      flush();
      const head = cells(line).map(parseInline);
      const rows: Inline[][][] = [];
      for (i += 2; i < lines.length && isRow(lines[i]); i++) rows.push(cells(lines[i]).map(parseInline));
      i--;
      blocks.push({ t: "table", head, rows });
      continue;
    }
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    const ul = /^\s*[-*•]\s+(.*)$/.exec(line);
    const ol = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (h) {
      flush();
      blocks.push({ t: "h", level: h[1].length as 1 | 2 | 3, inline: parseInline(h[2]) });
    } else if (ul || ol) {
      const kind = ul ? "ul" : "ol";
      if (para.length) {
        blocks.push({ t: "p", inline: parseInline(para.join(" ")) });
        para = [];
      }
      if (list && list.t !== kind) {
        blocks.push(list);
        list = null;
      }
      list ??= { t: kind, items: [] };
      list.items.push(parseInline((ul ?? ol)![1]));
    } else if (line.trim() === "") {
      flush();
    } else {
      if (list) {
        blocks.push(list);
        list = null;
      }
      para.push(line.trim());
    }
  }
  flush();
  return blocks;
}

/**
 * Text to show for an assistant message. If the model replied with raw JSON instead of readable
 * Markdown, show its prose field or a neutral sentence; raw JSON is never shown to the user.
 */
export function displayText(text: string): string {
  const t = text.trim();
  if (!/^[[{]/.test(t)) return text;
  try {
    const data: unknown = JSON.parse(t);
    if (data && typeof data === "object" && !Array.isArray(data)) {
      for (const k of ["summary", "message", "text", "answer"]) {
        const v = (data as Record<string, unknown>)[k];
        if (typeof v === "string" && v.trim()) return v;
      }
    }
    return "Done. See the actions above for details.";
  } catch {
    return text; // not valid JSON: show as written
  }
}
