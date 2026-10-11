/**
 * Twins now come from the backend (GET /twins lists only the signed-in user's own twins), so there is no browser-side list any more.
 * The only thing remembered locally is WHICH of your twins was last open, keyed by your user id. It is just a twin id: no credentials, no tokens, no glucose values.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export const isTwinId = (s: string): boolean => UUID.test(s.trim().toLowerCase());
const key = (userId: string): string => `glycotwin.active.${userId}.v2`;

export function loadActive(userId: string, storage: Pick<Storage, "getItem"> = localStorage): string | null {
  try { const v = storage.getItem(key(userId)); return v && isTwinId(v) ? v : null; } catch { return null; }
}
export function saveActive(userId: string, id: string | null, storage: Pick<Storage, "setItem" | "removeItem"> = localStorage): void {
  try { id ? storage.setItem(key(userId), id) : storage.removeItem(key(userId)); } catch { /* storage unavailable: the session still works */ }
}
