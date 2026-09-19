import { useState, type ReactElement } from "react";

/**
 * One pass over a JSON document. Order matters: strings are consumed before
 * numbers and literals, so digits or the word `null` inside a string are not
 * re-coloured. A string followed by a colon is a field name, the only
 * distinction that needs lookahead.
 */
const JSON_TOKEN = /("(?:\\.|[^"\\])*")(\s*:)|("(?:\\.|[^"\\])*")|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|\b(true|false|null)\b|([{}[\],:])/g;

const SYNTAX = {
  name: "var(--syntax-key)",
  string: "var(--syntax-string)",
  number: "var(--syntax-number)",
  literal: "var(--syntax-literal)",
  punctuation: "var(--syntax-punctuation)",
} as const;

function highlightJson(code: string): ReactElement[] {
  const out: ReactElement[] = [];
  let last = 0, n = 0;
  const push = (text: string, colour?: string) =>
    out.push(<span key={n++} style={colour ? { color: colour } : undefined}>{text}</span>);

  for (const m of code.matchAll(JSON_TOKEN)) {
    const at = m.index ?? 0;
    if (at > last) push(code.slice(last, at));
    if (m[1] !== undefined) { push(m[1], SYNTAX.name); push(m[2], SYNTAX.punctuation); }
    else if (m[3] !== undefined) push(m[3], SYNTAX.string);
    else if (m[4] !== undefined) push(m[4], SYNTAX.number);
    else if (m[5] !== undefined) push(m[5], SYNTAX.literal);
    else push(m[6], SYNTAX.punctuation);
    last = at + m[0].length;
  }
  if (last < code.length) push(code.slice(last));
  return out;
}

export function CodeBlock({ code, label, wrap, maxHeight = 320, language }: { code: string; label?: string; wrap?: boolean; maxHeight?: number; language?: "json" }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1200); } catch { /* clipboard blocked */ }
  };
  return (
    <div className="relative rounded-md border border-border bg-surface-2">
      {label && <div className="border-b border-border px-3 py-1 text-[11px] uppercase tracking-wide text-text-muted">{label}</div>}
      <button onClick={copy} className="absolute right-2 top-1.5 rounded-sm border border-border bg-surface px-1.5 text-[11px] text-text-2 hover:bg-surface-2">
        {copied ? "copied" : "copy"}
      </button>
      <pre className={`overflow-auto p-3 text-xs leading-relaxed text-text ${wrap ? "whitespace-pre-wrap break-words" : ""}`} style={{ maxHeight }}>
        {language === "json" ? highlightJson(code) : code}
      </pre>
    </div>
  );
}

/** Enough markdown for PR bodies: headings, bullets, fences, paragraphs, inline code. */
export function Markdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const out: ReactElement[] = [];
  let i = 0, key = 0;
  const inline = (s: string) => s.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).map((part, n) =>
    part.startsWith("`") && part.endsWith("`") ? <code key={n} className="rounded-sm bg-surface-2 px-1 text-[0.9em]">{part.slice(1, -1)}</code>
    : part.startsWith("**") && part.endsWith("**") ? <b key={n} className="text-text">{part.slice(2, -2)}</b>
    : <span key={n}>{part}</span>);
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("```")) {
      const buf: string[] = []; i++;
      while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]);
      i++;
      out.push(<pre key={key++} className="my-2 overflow-auto rounded-md bg-surface-2 p-2 text-xs">{buf.join("\n")}</pre>);
      continue;
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { out.push(<hr key={key++} className="my-3 border-border" />); i++; continue; }
    if (line.startsWith(">")) {
      const buf: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) buf.push(lines[i++].replace(/^>\s?/, ""));
      out.push(<blockquote key={key++} className="my-2 border-l-2 pl-3 text-sm text-text-2" style={{ borderColor: "var(--status-warning)" }}>{inline(buf.join(" "))}</blockquote>);
      continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) { out.push(<div key={key++} className={`mt-3 mb-1 font-semibold ${h[1].length <= 2 ? "text-base" : "text-sm"}`}>{inline(h[2])}</div>); i++; continue; }
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*]\s+/, ""));
      out.push(<ul key={key++} className="my-1 list-disc space-y-0.5 pl-5">{items.map((it, n) => <li key={n}>{inline(it)}</li>)}</ul>);
      continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*\d+\.\s+/, ""));
      out.push(<ol key={key++} className="my-1 list-decimal space-y-0.5 pl-5">{items.map((it, n) => <li key={n}>{inline(it)}</li>)}</ol>);
      continue;
    }
    if (line.startsWith("|")) {
      const rows: string[] = [];
      while (i < lines.length && lines[i].startsWith("|")) rows.push(lines[i++]);
      const cells = rows.filter((r) => !/^\|\s*-+/.test(r)).map((r) => r.split("|").slice(1, -1).map((c) => c.trim()));
      out.push(<table key={key++} className="my-2 text-xs"><tbody>{cells.map((r, ri) => <tr key={ri} className={ri === 0 ? "font-semibold" : ""}>{r.map((c, ci) => <td key={ci} className="border border-border px-2 py-1">{inline(c)}</td>)}</tr>)}</tbody></table>);
      continue;
    }
    if (line.trim() === "") { i++; continue; }
    const buf: string[] = [];
    while (i < lines.length && lines[i].trim() !== "" && !/^(#{1,4}\s|```|\s*[-*]\s|\s*\d+\.\s|\||>)/.test(lines[i])) buf.push(lines[i++]);
    out.push(<p key={key++} className="my-1 text-sm text-text-2">{inline(buf.join(" "))}</p>);
  }
  return <div className="text-sm">{out}</div>;
}
