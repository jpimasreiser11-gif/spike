import { dicts, lang } from "../i18n";

/** Bundled instruction profiles have translated summaries; user overrides always keep their own text. */
export function SkillDescription({ skill, locale = lang }: {
  skill: { name: string; source: string; description: string }; locale?: "es" | "en";
}) {
  const description = skill.source === "bundled" ? dicts[locale].bundledSkillDescriptions[skill.name] : undefined;
  return <p className="small">{description ?? skill.description}</p>;
}
