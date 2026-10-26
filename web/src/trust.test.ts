import { describe, expect, it } from "vitest";
import { dicts } from "./i18n";
import { applyEvent, emptyRun, runFromStored } from "./run";
import { citationText, fill, money, offerNotes, summaryText, tone } from "./trust";
import type { EscalationOffer } from "./types";

const es = dicts.es.trust;
const en = dicts.en.trust;

describe("summaryText", () => {
  it("lists verified, hypothesis and unchecked in that order, with the right plural, in both languages", () => {
    const counts = { verified: 3, hypothesis: 1, unchecked: 2 };
    expect(summaryText(counts, es)).toBe("3 verificadas · 1 hipótesis · 2 sin comprobar");
    expect(summaryText(counts, en)).toBe("3 verified · 1 hypothesis · 2 unchecked");
    expect(summaryText({ verified: 1, hypothesis: 2, unchecked: 1 }, es)).toBe("1 verificada · 2 hipótesis · 1 sin comprobar");
    expect(summaryText({ verified: 1, hypothesis: 2, unchecked: 1 }, en)).toBe("1 verified · 2 hypotheses · 1 unchecked");
  });
  it("leaves out what is zero", () => {
    expect(summaryText({ verified: 0, hypothesis: 0, unchecked: 4 }, es)).toBe("4 sin comprobar");
    expect(summaryText({ verified: 2, hypothesis: 0, unchecked: 0 }, en)).toBe("2 verified");
    expect(summaryText({ verified: 0, hypothesis: 0, unchecked: 0 }, en)).toBe("");
  });
  it("has the same labels in both languages", () => {
    expect(Object.keys(es.why).sort()).toEqual(Object.keys(en.why).sort());
    expect(Object.keys(es.citation).sort()).toEqual(Object.keys(en.citation).sort());
    expect(Object.keys(es.escalate).sort()).toEqual(Object.keys(en.escalate).sort());
    expect(Object.keys(es.settings).sort()).toEqual(Object.keys(en.settings).sort());
  });
});

describe("tone", () => {
  it("is warn with anything unchecked, mixed with only hypotheses and ok with everything verified", () => {
    expect(tone({ verified: 2, hypothesis: 1, unchecked: 1 })).toBe("warn");
    expect(tone({ verified: 2, hypothesis: 1, unchecked: 0 })).toBe("mixed");
    expect(tone({ verified: 2, hypothesis: 0, unchecked: 0 })).toBe("ok");
  });
});

describe("the offer", () => {
  const offer: EscalationOffer = { provider_id: "openai", name: "OpenAI", model: "gpt", paid: true, blocked: null, files: "none", tokens_in: 1234, tokens_out: 2048, cost: 0.0229 };
  it("states the size, the cost at the user's prices and what happens to their files", () => {
    expect(offerNotes(offer, en)).toEqual(["≈ 1234 input tokens, up to 2048 output", "Estimated cost ≈ 0.02, at the prices you entered"]);
    expect(offerNotes({ ...offer, cost: 0.00123, files: "withheld" }, en)[1]).toContain("0.0012");
    expect(offerNotes({ ...offer, files: "sent" }, es).at(-1)).toBe(es.escalate.filesSent);
    expect(offerNotes({ ...offer, files: "withheld" }, es).at(-1)).toBe(es.escalate.filesWithheld);
  });
  it("says so when there is no price instead of inventing a cost", () => {
    expect(offerNotes({ ...offer, cost: null }, es)[1]).toBe(es.escalate.noPrice);
  });
  it("formats money and templates", () => {
    expect([money(0), money(1.5), money(0.0123), money(0.00004)]).toEqual(["0", "1.50", "0.01", "<0.0001"]);
    expect(fill("Preguntar a {name} ({n})", { name: "OpenAI", n: 3 })).toBe("Preguntar a OpenAI (3)");
    expect(fill("{x}", {})).toBe("{x}");
  });
});

describe("citationText", () => {
  it("says what the check found, and which number the source lacks", () => {
    const base = { ref: "notas.md", how: "marked" as const, ok: false };
    expect(citationText({ ...base, status: "ok", ok: true, label: "notas.md" }, en)).toBe("fragment found in notas.md");
    expect(citationText({ ...base, status: "no_source" }, es)).toBe("esa fuente no está entre las de esta respuesta: notas.md");
    expect(citationText({ ...base, status: "no_fragment", label: "notas.md" }, en)).toBe("that fragment is not in notas.md");
    expect(citationText({ ...base, status: "unsupported", label: "notas.md", missing: ["90"] }, es))
      .toBe("la fuente no respalda esta frase (notas.md) · falta en la fuente: 90");
  });
});

describe("the trust event in a run", () => {
  const trust = {
    claims: [{ id: "c1", text: "El norte ingresa 90 €.", label: "verified", why: "tool" }],
    counts: { verified: 1, hypothesis: 0, unchecked: 0 }, sources: [], verifier_failed: false, private: false,
  };
  it("is kept live and after a reload", () => {
    const live = applyEvent(emptyRun(), { type: "trust", ...trust });
    expect(live.trust?.counts.verified).toBe(1);
    expect(live.trust).not.toHaveProperty("type");
    const stored = runFromStored({ id: "m1", role: "assistant", content: "ok", created: 0, meta: { trust } } as any);
    expect(stored.trust?.claims[0].label).toBe("verified");
    expect(runFromStored({ id: "m2", role: "assistant", content: "ok", created: 0, meta: {} } as any).trust).toBeUndefined();
  });
});
