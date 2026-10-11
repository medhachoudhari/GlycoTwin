/**
 * The backend deliberately has no endpoint that lists twins (privacy), so this browser remembers the twins it created or opened.
 * Only an id and a pseudonymous label are stored, in localStorage; no glucose values, no research data.
 */
export interface RegistryEntry { id: string; label: string; addedAt: string }
const KEY = "glycotwin.twins.v1";
const ACTIVE = "glycotwin.active.v1";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export const isTwinId = (s: string): boolean => UUID.test(s.trim().toLowerCase());

export function loadRegistry(storage: Pick<Storage, "getItem"> = localStorage): RegistryEntry[] {
  try {
    const raw = JSON.parse(storage.getItem(KEY) ?? "[]");
    if (!Array.isArray(raw)) return [];
    return raw.filter((e): e is RegistryEntry => e && typeof e.id === "string" && isTwinId(e.id) && typeof e.label === "string");
  } catch { return []; }
}
export function saveRegistry(entries: RegistryEntry[], storage: Pick<Storage, "setItem"> = localStorage): void {
  try { storage.setItem(KEY, JSON.stringify(entries.slice(0, 50))); } catch { /* storage unavailable: the session still works */ }
}
export function upsert(entries: RegistryEntry[], e: { id: string; label: string }): RegistryEntry[] {
  const rest = entries.filter((x) => x.id !== e.id);
  return [{ id: e.id, label: e.label, addedAt: new Date().toISOString() }, ...rest];
}
export function loadActive(storage: Pick<Storage, "getItem"> = localStorage): string | null {
  try { const v = storage.getItem(ACTIVE); return v && isTwinId(v) ? v : null; } catch { return null; }
}
export function saveActive(id: string | null, storage: Pick<Storage, "setItem" | "removeItem"> = localStorage): void {
  try { id ? storage.setItem(ACTIVE, id) : storage.removeItem(ACTIVE); } catch { /* ignore */ }
}
