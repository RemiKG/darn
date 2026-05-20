/**
 * Formatting helpers. Every live numeral renders in JetBrains Mono via the
 * `.num`/`.mono` classes (see tokens.css) — these helpers only build strings.
 * Unknown values format to "—" (the honest dash), never to invented numbers.
 */

const DASH = "—";

function bad(v: number | null | undefined): v is null | undefined {
  return v === null || v === undefined || Number.isNaN(v);
}

/** 461 → "07:41". Minutes are total minutes (no hour rollover — wall clocks read mm:ss). */
export function mmss(seconds: number | null | undefined): string {
  if (bad(seconds)) {
    return DASH;
  }
  const total = Math.max(0, Math.floor(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/** 2280 → "38 min ago" (health-card footer style). */
export function relTime(agoSeconds: number | null | undefined): string {
  if (bad(agoSeconds)) {
    return DASH;
  }
  const s = Math.max(0, Math.round(agoSeconds));
  if (s < 60) {
    return `${s} s ago`;
  }
  const min = Math.round(s / 60);
  if (min < 90) {
    return `${min} min ago`;
  }
  const h = Math.round(min / 60);
  if (h < 36) {
    return `${h} h ago`;
  }
  const d = Math.round(h / 24);
  return `${d} d ago`;
}

/** "9b1f2e0a77c1..." → "9b1f2e0" */
export function shortSha(sha: string | null | undefined): string {
  if (!sha) {
    return DASH;
  }
  return sha.slice(0, 7);
}

/** 0.0381 → "$0.0381" (4 decimal places — token costs are small and honest). */
export function money(usd: number | null | undefined): string {
  if (bad(usd)) {
    return DASH;
  }
  return `$${usd.toFixed(4)}`;
}

/**
 * 14.2 → "14.2 %", 0.31 → "0.31 %" (2dp under 1, 1dp above).
 * Pass `digits` to pin it.
 */
export function pct(value: number | null | undefined, digits?: number): string {
  if (bad(value)) {
    return DASH;
  }
  const d = digits ?? (Math.abs(value) < 1 ? 2 : 1);
  return `${value.toFixed(d)} %`;
}

/** 412.4 → "412 ms" */
export function ms(value: number | null | undefined): string {
  if (bad(value)) {
    return DASH;
  }
  return `${Math.round(value)} ms`;
}

/** Epoch seconds → "02:57:14" (UTC clock — matches "started 02:57:14 UTC"). */
export function utcClock(epochSeconds: number | null | undefined): string {
  if (bad(epochSeconds)) {
    return DASH;
  }
  const d = new Date(epochSeconds * 1000);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mi = String(d.getUTCMinutes()).padStart(2, "0");
  const ss = String(d.getUTCSeconds()).padStart(2, "0");
  return `${hh}:${mi}:${ss}`;
}

/** 18412 → "18 412" (thin-grouped token counts, e.g. "18 412 in / 1 207 out"). */
export function groupedInt(value: number | null | undefined): string {
  if (bad(value)) {
    return DASH;
  }
  return Math.round(value)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

export const honestDash = DASH;
