/** Checks for the number and text fields of Settings, matching the server's rules (spike/server/settings_clean.py). */

export type Parsed = { ok: true; value: number | null } | { ok: false };

/** A number from `min` to `max`; an empty field means "not set" (null). */
export function parseOptionalNumber(raw: string, min: number, max: number): Parsed {
  if (raw.trim() === "") return { ok: true, value: null };
  const n = Number(raw);
  return Number.isFinite(n) && n >= min && n <= max ? { ok: true, value: n } : { ok: false };
}

/** A whole number from `min` to `max`; empty means "not set". */
export function parseCount(raw: string, min: number, max: number): Parsed {
  const p = parseOptionalNumber(raw, min, max);
  return p.ok && p.value !== null && !Number.isInteger(p.value) ? { ok: false } : p;
}

/** Provider ids are lower-case letters, digits and hyphens (empty = the preset's own id). */
export const providerIdOk = (id: string) => id === "" || /^[a-z0-9][a-z0-9-]{0,40}$/.test(id);

/** The provider address must be http(s). */
export const urlOk = (url: string) => /^https?:\/\/\S+$/.test(url.trim());
