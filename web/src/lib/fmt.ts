export const pct = (v: number | null | undefined, digits = 1) => v == null ? "—" : `${(v * 100).toFixed(digits)}%`;
export const num = (v: number | null | undefined, digits = 0) => v == null ? "—" : v.toFixed(digits);
export const secs = (v: number | null | undefined, digits = 2) => v == null ? "—" : `${v.toFixed(digits)}s`;
export const usd = (v: number | null | undefined) => v == null ? "—" : `$${v.toFixed(2)}`;

/** HH:MM:SS in the viewer's local time. */
export function clock(ts: string | null | undefined): string {
  if (!ts) return "";
  const d = new Date(ts);
  return isNaN(d.getTime()) ? ts : d.toLocaleTimeString([], { hour12: false });
}

/** HH:MM as written in the telemetry (UTC), no timezone shifting. */
export const utcClock = (ts: string) => ts.length >= 16 ? ts.slice(11, 16) : ts;

export function elapsed(ms: number | null | undefined): string {
  if (ms == null || ms < 0) return "—";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${String(s % 60).padStart(2, "0")}s`;
}

export const since = (iso: string, now = Date.now()) => elapsed(now - new Date(iso).getTime());

/** Strip an absolute repo prefix so paths read as repo-relative. */
export function shortPath(path: string | undefined | null): string {
  if (!path) return "";
  const marker = path.indexOf("/tessera-platform/");
  if (marker !== -1) return path.slice(marker + "/tessera-platform/".length);
  const scratch = path.indexOf("/shape-run/");
  if (scratch !== -1) return path.slice(scratch + "/shape-run/".length);
  return path;
}
