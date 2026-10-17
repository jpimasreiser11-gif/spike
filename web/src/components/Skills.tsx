import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { lang } from "../i18n";
import type { Settings, SkillInfo } from "../types";
import { IconTrash, IconUpload } from "./Icons";

const K = lang === "es"
  ? {
      intro: "Las skills son instrucciones en formato SKILL.md. Con modelos locales pequeños, SPIKE elige la skill según tu mensaje y la añade al prompt; con modelos de API, el modelo ve la lista y carga la que necesita.",
      mode: "Cómo se eligen", auto: "Automático (recomendado)", router: "Siempre SPIKE (palabras clave)", model: "Siempre el modelo", off: "Desactivadas",
      bundled: "incluida", user: "tuya", any: "cualquier especialista", importSkill: "Importar skill (.zip)", exportPack: "Exportar pack", importPack: "Importar pack",
      packHint: "Un pack reúne tus especialistas personalizados, tus skills y tus conectores propios, sin claves.", remove: "Eliminar", imported: "Importado",
    }
  : {
      intro: "Skills are instructions in SKILL.md format. With small local models SPIKE picks the skill from your message and adds it to the prompt; with API models the model sees the list and loads what it needs.",
      mode: "How they are chosen", auto: "Automatic (recommended)", router: "Always SPIKE (keywords)", model: "Always the model", off: "Off",
      bundled: "built-in", user: "yours", any: "any specialist", importSkill: "Import skill (.zip)", exportPack: "Export pack", importPack: "Import pack",
      packHint: "A pack bundles your custom specialists, your skills and your own connectors, without keys.", remove: "Remove", imported: "Imported",
    };

export function Skills({ settings, save }: { settings: Settings; save: (p: Partial<Settings>) => void }) {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const skillInput = useRef<HTMLInputElement>(null);
  const packInput = useRef<HTMLInputElement>(null);
  const load = () => api.get<SkillInfo[]>("/api/skills").then(setSkills).catch((e) => setErr(String(e.message)));
  useEffect(() => { load(); }, [settings.disabled_skills]);

  const upload = async (path: string, file: File | undefined, input: HTMLInputElement | null) => {
    if (!file) return;
    setErr(""); setMsg("");
    try {
      const r = await api.upload<Record<string, string[]>>("POST", path, file);
      setMsg(`${K.imported}: ${Object.values(r).flat().join(", ") || "—"}`);
    } catch (e) { setErr(String((e as Error).message)); }
    if (input) input.value = "";
    load();
  };

  const toggle = async (s: SkillInfo) => {
    await api.put(`/api/skills/${s.name}`, { enabled: !s.enabled });
    const disabled = s.enabled ? [...settings.disabled_skills, s.name] : settings.disabled_skills.filter((n) => n !== s.name);
    save({ disabled_skills: disabled });
  };

  return (
    <div className="form">
      <p className="small muted">{K.intro}</p>
      <label className="field inline"><span>{K.mode}</span>
        <select value={settings.skill_mode} onChange={(e) => save({ skill_mode: e.target.value as Settings["skill_mode"] })}>
          {(["auto", "router", "model", "off"] as const).map((m) => <option key={m} value={m}>{K[m]}</option>)}
        </select>
      </label>
      <div className="row">
        <button className="btn" onClick={() => skillInput.current?.click()}><IconUpload size={14} /> {K.importSkill}</button>
        <a className="btn" href="/api/pack/export" download>{K.exportPack}</a>
        <button className="btn" onClick={() => packInput.current?.click()}><IconUpload size={14} /> {K.importPack}</button>
        <input ref={skillInput} type="file" accept=".zip" hidden data-testid="skill-import" onChange={(e) => upload("/api/skills/import", e.target.files?.[0], skillInput.current)} />
        <input ref={packInput} type="file" accept=".zip" hidden data-testid="pack-import" onChange={(e) => upload("/api/pack/import", e.target.files?.[0], packInput.current)} />
      </div>
      <small className="muted">{K.packHint}</small>
      {msg && <div className="flash-box">{msg}</div>}
      {err && <div className="error-box" role="alert">{err}</div>}
      {skills.map((s) => (
        <div key={s.name} className="card" data-skill={s.name}>
          <div className="card-head">
            <label className="check"><input type="checkbox" checked={s.enabled} onChange={() => toggle(s)} /><code>{s.name}</code></label>
            <span className="badge">{s.source === "user" ? K.user : K.bundled}</span>
            {s.license && <span className="badge">{s.license}</span>}
            <div className="spacer" />
            {s.source === "user" && <button className="icon-btn" aria-label={`${K.remove}: ${s.name}`} onClick={() => api.del(`/api/skills/${s.name}`).then(load)}><IconTrash size={14} /></button>}
          </div>
          <p className="small">{s.description}</p>
          <p className="small muted">{s.specialists.length ? s.specialists.join(", ") : K.any}{s.keywords.length > 0 && ` · ${s.keywords.slice(0, 8).join(", ")}`}</p>
        </div>
      ))}
    </div>
  );
}
