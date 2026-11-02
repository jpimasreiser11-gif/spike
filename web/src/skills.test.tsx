import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { dicts } from "./i18n";
import { SkillDescription } from "./components/SkillDescription";

describe("bundled skill descriptions", () => {
  it("provides eighteen meaningful descriptions in Spanish and English", () => {
    const es = dicts.es.bundledSkillDescriptions;
    const en = dicts.en.bundledSkillDescriptions;
    expect(Object.keys(es)).toHaveLength(18);
    expect(Object.keys(en)).toEqual(Object.keys(es));
    for (const name of Object.keys(es)) {
      expect(es[name].length).toBeGreaterThan(20);
      expect(en[name].length).toBeGreaterThan(20);
      expect(es[name]).not.toEqual(en[name]);
    }
  });
  it("localizes all five creator templates", () => {
    for (const name of ["landing-page", "report-creator", "deck-creator", "dashboard-creator", "data-app-creator"]) {
      for (const locale of ["es", "en"] as const) {
        const skill = { name, description: "fallback", source: "bundled" };
        expect(renderToStaticMarkup(<SkillDescription skill={skill} locale={locale} />))
          .toContain(dicts[locale].bundledSkillDescriptions[name]);
      }
    }
  });
  it("localizes bundled profiles and preserves custom and older descriptions", () => {
    const base = { name: "localization", description: "Custom description", source: "bundled" };
    expect(renderToStaticMarkup(<SkillDescription skill={base} locale="es" />)).toContain("glosario");
    expect(renderToStaticMarkup(<SkillDescription skill={base} locale="en" />)).toContain("glossary");
    expect(renderToStaticMarkup(<SkillDescription skill={{ ...base, source: "user" }} locale="es" />)).toContain("Custom description");
    expect(renderToStaticMarkup(<SkillDescription skill={{ ...base, name: "older" }} locale="es" />)).toContain("Custom description");
  });
});
