import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";
import type { Settings, SkillInfo } from "../types";
import { SkillDescription } from "./SkillDescription";
import "./ForgeSkills.css";

const MAX_SKILLS = 3; // ChatBody.skills also caps explicit choices at three.

/** Per-run instructions. Importing stores a local skill; only the user's selection accompanies an approved plan. */
export function ForgeSkills({ selected, onChange, onReady, disabled = false }: {
  selected: string[]; onChange: (names: string[]) => void; onReady: (ready: boolean) => void; disabled?: boolean;
}) {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [off, setOff] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const epoch = useRef(0);
  const working = useRef(false);
  const current = useRef({ selected, onChange, onReady });
  current.current = { selected, onChange, onReady };

  const load = async (id: number) => {
    try {
      const [inventory, settings] = await Promise.all([
        api.get<SkillInfo[]>("/api/skills"), api.get<Pick<Settings, "skill_mode">>("/api/settings"),
      ]);
      if (epoch.current !== id) return;
      if (!Array.isArray(inventory) || inventory.some((s) => !s || typeof s.name !== "string" ||
        typeof s.description !== "string" || typeof s.enabled !== "boolean") ||
        !settings || !["auto", "router", "model", "off"].includes(settings.skill_mode)) throw new Error("invalid inventory");
      const stopped = settings.skill_mode === "off";
      setSkills(inventory); setOff(stopped);
      const names = new Set(inventory.filter((s) => s.enabled).map((s) => s.name));
      const kept = stopped ? [] : current.current.selected.filter((n) => names.has(n)).slice(0, MAX_SKILLS);
      if (kept.length !== current.current.selected.length) current.current.onChange(kept);
      current.current.onReady(true);
    } catch {
      if (epoch.current === id) setError(t.forgeSkills.loadFailed);
    } finally {
      if (epoch.current === id) { setLoading(false); working.current = false; }
    }
  };
  const refresh = () => {
    if (working.current) return;
    working.current = true; setLoading(true); setError(""); current.current.onReady(false);
    void load(++epoch.current);
  };
  useEffect(() => { refresh(); return () => { epoch.current += 1; working.current = false; }; }, []);

  const upload = async (file: File | undefined) => {
    if (!file || working.current || disabled) return;
    setMessage(""); setError("");
    if (!/\.zip$/i.test(file.name) || file.size > 20_000_000) {
      setError(t.forgeSkills.invalid); if (fileInput.current) fileInput.current.value = ""; return;
    }
    working.current = true; setLoading(true); current.current.onReady(false);
    const id = ++epoch.current;
    try {
      const result = await api.upload<{ names: string[] }>("POST", "/api/skills/import", file);
      if (epoch.current !== id) return;
      if (!result || !Array.isArray(result.names) || !result.names.length ||
        result.names.some((name) => typeof name !== "string" || !name.trim())) throw new Error("invalid import result");
      setMessage(`${t.forgeSkills.imported}: ${result.names.join(", ")}`);
      await load(id);
    } catch {
      if (epoch.current === id) { setError(t.forgeSkills.importFailed); setLoading(false); working.current = false; }
    } finally {
      if (epoch.current === id && fileInput.current) fileInput.current.value = "";
    }
  };
  const matches = skills.filter((s) => `${s.name} ${s.description}`.toLowerCase().includes(query.trim().toLowerCase()));
  const summary = loading ? t.forgeSkills.loading : error || (off ? t.forgeSkills.offShort :
    selected.length ? `${selected.length} · ${selected.join(", ")}` : t.forgeSkills.auto);
  return <details className="forge-skills">
    <summary><b>{t.forgeSkills.title}</b><span>{summary}</span></summary>
    <div className="forge-skills-body">
      <p className="small muted">{t.forgeSkills.hint}</p>
      {off && <p className="notice">{t.forgeSkills.off}</p>}
      {disabled && <p className="small muted">{t.forgeSkills.unavailable}</p>}
      <div className="row">
        <button type="button" className="btn small" disabled={loading || disabled} onClick={() => fileInput.current?.click()}>{t.forgeSkills.import}</button>
        <button type="button" className="btn small" data-skills-refresh disabled={loading || disabled} onClick={refresh}>{t.forgeSkills.refresh}</button>
        <input ref={fileInput} type="file" accept=".zip" hidden onChange={(e) => void upload(e.target.files?.[0])} />
      </div>
      {loading && <p role="status">{t.forgeSkills.loading}</p>}
      {message && <p role="status">{message}</p>}
      {error && <p role="alert">{error}</p>}
      {selected.length >= MAX_SKILLS && <p className="small muted">{t.forgeSkills.limit}</p>}
      <label className="field"><span>{t.forgeSkills.search}</span><input type="search" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
      <div className="forge-skills-list">
        {matches.map((s) => <article key={s.name}>
          <label className="check"><input type="checkbox" data-forge-skill={s.name} checked={selected.includes(s.name)}
            disabled={disabled || loading || !!error || off || !s.enabled || (selected.length >= MAX_SKILLS && !selected.includes(s.name))}
            onChange={(e) => onChange(e.target.checked ? [...selected, s.name].slice(0, MAX_SKILLS) : selected.filter((n) => n !== s.name))} /><code>{s.name}</code></label>
          <span className="badge">{s.source === "user" ? t.forgeSkills.user : t.forgeSkills.bundled}</span>
          {!s.enabled && <span className="badge">{t.forgeSkills.disabled}</span>}
          {s.license && <span className="badge">{s.license}</span>}
          <SkillDescription skill={s} />
        </article>)}
        {!loading && !error && !matches.length && <p className="muted">{t.forgeSkills.empty}</p>}
      </div>
    </div>
  </details>;
}
