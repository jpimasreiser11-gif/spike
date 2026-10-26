import { t } from "./i18n";
import type { Isolation } from "./types";

type Why = Pick<Isolation, "reason" | "code">;

/** Why a run is not isolated, in the user's language when SPIKE knows the code; what the system said stays as it is. */
export function reasonText(why: Why, strings: typeof t.isolation = t.isolation): string {
  const known = strings.reasons[why.code];
  if (!known) return why.reason;
  const detail = why.code.endsWith("_failed") ? why.reason.split(": ").slice(1).join(": ") : "";
  return detail ? `${known}: ${detail}` : known;
}

/** The line the permission card shows: "isolated (bwrap): …" or "not isolated: <reason>". */
export function isolationText(iso: Isolation, strings: typeof t.isolation = t.isolation): string {
  return iso.isolated ? `${strings.yes} (${iso.backend}): ${strings.detail}` : `${strings.no}: ${reasonText(iso, strings)}`;
}
