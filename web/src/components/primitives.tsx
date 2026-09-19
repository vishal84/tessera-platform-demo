import type { ReactNode } from "react";
import type { Persona } from "../api/types";

export type Tone = "good" | "warning" | "serious" | "critical" | "info" | "neutral";

export function StatusPill({ tone, children, pulse, className = "" }:
  { tone: Tone; children: ReactNode; pulse?: boolean; className?: string }) {
  const c = `var(--status-${tone})`;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 text-xs font-medium whitespace-nowrap ${className}`}
      style={{ color: c, borderColor: `color-mix(in srgb, ${c} 45%, transparent)`, background: `color-mix(in srgb, ${c} 12%, transparent)` }}>
      <span className={`h-1.5 w-1.5 rounded-full ${pulse ? "pulse" : ""}`} style={{ background: c }} />
      {children}
    </span>
  );
}

export const PERSONA_LABEL: Record<Persona, string> = { sre: "SRE", swe: "SWE", ds: "Data scientist", claude: "Claude", system: "System" };

export function personaColor(p: Persona): string {
  return p === "system" ? "var(--status-neutral)" : `var(--persona-${p})`;
}

export function PersonaChip({ persona, small, onAccent, className = "" }:
  { persona: Persona; small?: boolean; onAccent?: boolean; className?: string }) {
  const c = personaColor(persona);
  // The 14% tint below assumes the chip sits on a surface. On an accent fill --
  // a primary button -- the thing underneath is the accent itself, and a
  // mid-tone persona colour over it lands at about 1.2:1 in both themes, which
  // is unreadable. Sitting the chip on the accent's own contrast colour keeps
  // the persona hue and buys 5.5:1 (light) to 10:1 (dark). Recolouring the text
  // alone does not help: orange or green straight on the fill is still ~1.3:1.
  const style = onAccent
    ? { color: c, background: "var(--color-accent-contrast)" }
    : { color: c, background: `color-mix(in srgb, ${c} 14%, transparent)` };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-sm px-1.5 ${small ? "text-[10px] py-0" : "text-xs py-0.5"} font-semibold uppercase tracking-wide whitespace-nowrap ${className}`}
      style={style}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: c }} />
      {PERSONA_LABEL[persona]}
    </span>
  );
}

export function Card({ title, actions, children, className = "", tone }:
  { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; tone?: Tone }) {
  const border = tone ? `color-mix(in srgb, var(--status-${tone}) 55%, var(--color-border))` : undefined;
  return (
    <section className={`rounded-lg border border-border bg-surface shadow-1 ${className}`} style={border ? { borderColor: border } : undefined}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
          <h2 className="text-sm font-semibold text-text">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function MetricTile({ label, value, unit, sub, tone = "neutral", hero }:
  { label: string; value: string; unit?: string; sub?: ReactNode; tone?: Tone; hero?: boolean }) {
  const c = `var(--status-${tone})`;
  return (
    <div className="rounded-md border border-border bg-surface p-3 shadow-1" style={{ borderLeft: `3px solid ${c}` }}>
      <div className="text-xs font-medium uppercase tracking-wide text-text-muted">{label}</div>
      <div className={`mt-1 font-semibold tabular text-text ${hero ? "text-3xl leading-none" : "text-xl"}`}>
        {value}{unit && <span className="ml-1 text-sm font-normal text-text-2">{unit}</span>}
      </div>
      {sub && <div className="mt-1 text-xs text-text-2">{sub}</div>}
    </div>
  );
}

export function Button({ children, onClick, disabled, variant = "secondary", persona, title, className = "", type = "button" }:
  { children: ReactNode; onClick?: () => void; disabled?: boolean; variant?: "primary" | "secondary" | "danger" | "ghost";
    persona?: Persona; title?: string; className?: string; type?: "button" | "submit" }) {
  const base = "inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed";
  const styles: Record<string, string> = {
    // disabled overrides the fill itself rather than fading it: opacity fades
    // fill and text toward the same surface colour beneath them, and since
    // accent-contrast is already chosen to sit near that surface colour, the
    // two collapse into each other -- e.g. white text at 50% opacity over a
    // white card stays white, while the blue fill fades toward white too,
    // landing both within a point of each other. Falling back to the same
    // muted surface/text pairing the secondary variant uses keeps a real gap.
    primary: "bg-accent text-accent-contrast hover:brightness-110 disabled:bg-surface-2 disabled:text-text-muted disabled:hover:brightness-100",
    secondary: "border border-border bg-surface text-text hover:bg-surface-2 disabled:opacity-50",
    danger: "border text-status-critical hover:bg-surface-2 disabled:opacity-50",
    ghost: "text-text-2 hover:bg-surface-2 disabled:opacity-50",
  };
  return (
    <button type={type} onClick={onClick} disabled={disabled} title={title} className={`${base} ${styles[variant]} ${className}`}
      style={variant === "danger" ? { borderColor: "color-mix(in srgb, var(--status-critical) 50%, transparent)" } : undefined}>
      {persona && <PersonaChip persona={persona} small onAccent={variant === "primary" && !disabled} />}
      {children}
    </button>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded-sm border border-border bg-surface-2 px-1 font-mono text-[11px] text-text-2">{children}</kbd>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-md border border-dashed border-border px-4 py-6 text-center text-sm text-text-muted">{children}</div>;
}
