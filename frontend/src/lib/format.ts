export const fmt = (v: number | null | undefined, digits = 1): string => (v === null || v === undefined || !Number.isFinite(v) ? "n/a" : v.toFixed(digits));
export const pct = (p: number | null | undefined, digits = 0): string => (p === null || p === undefined || !Number.isFinite(p) ? "n/a" : `${(p * 100).toFixed(digits)}%`);
export const signed = (v: number, digits = 1): string => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(digits)}`;

/** Backend timestamps are naive UTC ISO strings. Show them as UTC, unambiguously. */
export function utcLabel(iso: string | null | undefined): string {
  if (!iso) return "n/a";
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}
export const shortId = (id: string): string => (id.length > 12 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id);

/** Local date-time-local input value -> ISO string the backend accepts (treated as UTC; the dataset is date-shifted, so absolute time is not meaningful). */
export function inputToIso(value: string): string {
  return value.length === 16 ? `${value}:00` : value;
}
export function addMinutesIso(iso: string, minutes: number): string {
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  return new Date(d.getTime() + minutes * 60000).toISOString().slice(0, 19);
}
export function newEventId(): string {
  const rnd = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID().slice(0, 8) : Math.random().toString(16).slice(2, 10);
  return `meal-${Date.now().toString(36)}-${rnd}`;
}
