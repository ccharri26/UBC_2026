// Display helpers. "—" stands for a missing value everywhere.

export const DASH = "—";

export function usd(x: number | null | undefined, digits = 2): string {
  if (x === null || x === undefined) return DASH;
  const abs = Math.abs(x).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${x < 0 ? "−" : ""}$${abs}`;
}

/** +$1.23 / −$1.23 / $0.00 */
export function signedUsd(x: number | null | undefined, digits = 2): string {
  if (x === null || x === undefined) return DASH;
  return x > 0 ? `+${usd(x, digits)}` : usd(x, digits);
}

/** Compact dollars for big flows: $12.3K, −$1.2M. */
export function compactUsd(x: number | null | undefined): string {
  if (x === null || x === undefined) return DASH;
  const abs = Math.abs(x).toLocaleString(undefined, { notation: "compact", maximumFractionDigits: 1 });
  return `${x < 0 ? "−" : x > 0 ? "+" : ""}$${abs}`;
}

export function pct(x: number | null | undefined, digits = 1, signed = false): string {
  if (x === null || x === undefined) return DASH;
  const s = `${(100 * x).toFixed(digits)}%`;
  return signed && x > 0 ? `+${s}` : s.replace("-", "−");
}

export function num(x: number | null | undefined, digits = 0): string {
  if (x === null || x === undefined) return DASH;
  return x.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function time(iso: string | null | undefined): string {
  if (!iso) return DASH;
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" });
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return DASH;
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export const tierName = (t: string) => (t === "smart_money" ? "Smart Money" : t === "basic" ? "Basic" : t);

export const short = (hex: string, head = 6, tail = 4) => `${hex.slice(0, head)}…${hex.slice(-tail)}`;

/** Tailwind text colour for a gain or loss. */
export const tone = (x: number | null | undefined) =>
  x === null || x === undefined || x === 0 ? "" : x > 0 ? "text-gain" : "text-loss";
