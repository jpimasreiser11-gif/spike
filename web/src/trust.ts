import { t } from "./i18n";
import type { CitationState, EscalationOffer, TrustLabel } from "./types";

type Strings = typeof t.trust;

export const LABELS: TrustLabel[] = ["verified", "hypothesis", "unchecked"];

/** "{n}" and "{name}" in a translated string. */
export const fill = (template: string, vars: Record<string, string | number>) =>
  template.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m));

/** "3 verificadas · 1 hipótesis · 2 sin comprobar": always in this order, the labels with none left out. */
export function summaryText(counts: Record<TrustLabel, number>, strings: Strings = t.trust): string {
  return LABELS.filter((l) => (counts[l] ?? 0) > 0)
    .map((l) => `${counts[l]} ${strings.words[l][counts[l] === 1 ? 0 : 1]}`)
    .join(" · ");
}

/** The chip's colour: everything verified, something only hypothesised, or something stated as fact with nothing behind it. */
export const tone = (counts: Record<TrustLabel, number>): "ok" | "mixed" | "warn" =>
  counts.unchecked > 0 ? "warn" : counts.hypothesis > 0 ? "mixed" : "ok";

/** A cost as the user's prices give it: from a cent up to the cent, smaller amounts to four places. */
export const money = (cost: number) => (cost === 0 ? "0" : cost >= 0.01 ? cost.toFixed(2) : cost >= 0.0001 ? cost.toFixed(4) : "<0.0001");

/** What the offer to ask a provider says about it, line by line: size, cost and what happens to the user's files. */
export function offerNotes(o: EscalationOffer, strings: Strings = t.trust): string[] {
  const e = strings.escalate;
  return [
    fill(e.tokens, { in: o.tokens_in, out: o.tokens_out }),
    o.cost === null ? e.noPrice : fill(e.cost, { cost: money(o.cost) }),
    ...(o.files === "sent" ? [e.filesSent] : o.files === "withheld" ? [e.filesWithheld] : []),
  ];
}

/** What one citation check found, in the user's language. */
export function citationText(c: CitationState, strings: Strings = t.trust): string {
  const w = strings.citation;
  const where = c.label || c.ref;
  const base = c.status === "ok" ? `${w.ok} ${where}` : c.status === "no_source" ? `${w.no_source}: ${c.ref}`
    : c.status === "no_fragment" ? `${w.no_fragment} ${where}` : `${w.unsupported} (${where})`;
  return c.missing?.length ? `${base} · ${w.missing}: ${c.missing.join(", ")}` : base;
}
