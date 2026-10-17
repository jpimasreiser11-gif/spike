import { useEffect, useState } from "react";
import { api } from "../api";
import { lang } from "../i18n";
import type { Preset, ProviderInfo, Settings, Specialist, ToolInfo } from "../types";
import { Connectors } from "./Connectors";
import { Memory } from "./Memory";
import { Skills } from "./Skills";
import { IconClose, IconTrash } from "./Icons";
import { SpecMark } from "./SpecMark";

const L = lang === "es"
  ? {
      title: "Ajustes", general: "General", providers: "Proveedores", specialists: "Especialistas", tools: "Herramientas", skills: "Skills", connectors: "Conectores", memory: "Memoria", engine: "Motor local",
      instructions: "Instrucciones personalizadas", instructionsHint: "Se aplican a todos los especialistas y proveedores. SPIKE las añade a su propio prompt de sistema, así que funcionan igual con modelos locales y externos.",
      planner: "Planificador con IA para tareas de varias disciplinas", parallel: "Ejecutar subtareas en paralelo (recomendado solo con APIs externas)", toolsOn: "Permitir herramientas",
      temperature: "Temperatura (vacío = la del modelo)", maxTokens: "Máximo de tokens por respuesta", reasoning: "Modo razonamiento", rDefault: "Por defecto del modelo", rOn: "Activado", rOff: "Desactivado",
      save: "Guardar", saved: "Guardado", add: "Añadir proveedor", preset: "Plantilla", key: "API key", keySaved: "clave guardada", model: "Modelo", baseUrl: "URL base",
      allowPaid: "Permitir peticiones de pago", paidWarn: "Este proveedor puede cobrarte. SPIKE no enviará nada hasta que lo permitas.", test: "Probar conexión", default: "Predeterminado",
      makeDefault: "Usar por defecto", remove: "Eliminar", ok: "Conectado", models: "modelos", adapters: "adaptadores", bind: "Ejecutar en", inherit: "Proveedor por defecto",
      adapterStatus: "Adaptador", specInstr: "Instrucciones de este especialista", policy: "Política", allow: "Permitir", ask: "Preguntar", deny: "Bloquear",
      hw: "Hardware", rec: "Recomendado", modelPath: "Ruta del modelo GGUF", ctx: "Contexto (tokens)", start: "Iniciar", stop: "Detener", status: "Estado", running: "En marcha", stoppedS: "Parado",
      secrets: "Almacén de claves", pull: "Descarga el modelo base con: spike models pull", keyLink: "Obtener clave",
    }
  : {
      title: "Settings", general: "General", providers: "Providers", specialists: "Specialists", tools: "Tools", skills: "Skills", connectors: "Connectors", memory: "Memory", engine: "Local engine",
      instructions: "Custom instructions", instructionsHint: "Applied to every specialist and provider. SPIKE adds them to its own system prompt, so they work the same with local and external models.",
      planner: "AI planner for multi-domain tasks", parallel: "Run subtasks in parallel (recommended only with external APIs)", toolsOn: "Allow tools",
      temperature: "Temperature (empty = model default)", maxTokens: "Max tokens per answer", reasoning: "Reasoning mode", rDefault: "Model default", rOn: "On", rOff: "Off",
      save: "Save", saved: "Saved", add: "Add provider", preset: "Preset", key: "API key", keySaved: "key saved", model: "Model", baseUrl: "Base URL",
      allowPaid: "Allow paid requests", paidWarn: "This provider may bill you. SPIKE sends nothing until you allow it.", test: "Test connection", default: "Default",
      makeDefault: "Make default", remove: "Remove", ok: "Connected", models: "models", adapters: "adapters", bind: "Run on", inherit: "Default provider",
      adapterStatus: "Adapter", specInstr: "Instructions for this specialist", policy: "Policy", allow: "Allow", ask: "Ask", deny: "Block",
      hw: "Hardware", rec: "Recommended", modelPath: "GGUF model path", ctx: "Context (tokens)", start: "Start", stop: "Stop", status: "Status", running: "Running", stoppedS: "Stopped",
      secrets: "Key storage", pull: "Download the base model with: spike models pull", keyLink: "Get a key",
    };

type Tab = "general" | "providers" | "specialists" | "tools" | "skills" | "connectors" | "memory" | "engine";

export function SettingsDialog({ onClose, specialists, providers, reloadProviders }: {
  onClose: () => void;
  specialists: Specialist[];
  providers: ProviderInfo[];
  reloadProviders: () => void;
}) {
  const [tab, setTab] = useState<Tab>("general");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [flash, setFlash] = useState("");

  useEffect(() => {
    api.get<Settings>("/api/settings").then(setSettings);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const save = async (patch: Partial<Settings>) => {
    const next = await api.put<Settings>("/api/settings", patch);
    setSettings(next);
    setFlash(L.saved);
    setTimeout(() => setFlash(""), 1200);
  };

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={L.title}>
        <div className="modal-head">
          <h2>{L.title}</h2>
          {flash && <span className="flash">{flash}</span>}
          <button className="icon-btn" onClick={onClose} aria-label="Close"><IconClose /></button>
        </div>
        <div className="modal-body">
          <nav className="tabs" role="tablist">
            {(["general", "providers", "specialists", "tools", "skills", "connectors", "memory", "engine"] as Tab[]).map((k) => (
              <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{L[k]}</button>
            ))}
          </nav>
          <div className="tab-panel">
            {!settings ? null : tab === "general" ? (
              <General settings={settings} save={save} />
            ) : tab === "providers" ? (
              <Providers providers={providers} settings={settings} save={save} reload={reloadProviders} />
            ) : tab === "specialists" ? (
              <Specialists specialists={specialists} providers={providers} settings={settings} save={save} />
            ) : tab === "tools" ? (
              <Tools settings={settings} save={save} />
            ) : tab === "skills" ? (
              <Skills settings={settings} save={save} />
            ) : tab === "connectors" ? (
              <Connectors />
            ) : tab === "memory" ? (
              <Memory settings={settings} save={save} />
            ) : (
              <Engine settings={settings} save={save} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function General({ settings, save }: { settings: Settings; save: (p: Partial<Settings>) => void }) {
  const [instr, setInstr] = useState(settings.custom_instructions);
  return (
    <div className="form">
      <label className="field">
        <span>{L.instructions}</span>
        <textarea rows={6} value={instr} onChange={(e) => setInstr(e.target.value)} onBlur={() => instr !== settings.custom_instructions && save({ custom_instructions: instr })} />
        <small>{L.instructionsHint}</small>
      </label>
      <label className="check"><input type="checkbox" checked={settings.use_planner} onChange={(e) => save({ use_planner: e.target.checked })} />{L.planner}</label>
      <label className="check"><input type="checkbox" checked={settings.parallel} onChange={(e) => save({ parallel: e.target.checked })} />{L.parallel}</label>
      <label className="check"><input type="checkbox" checked={settings.tools_enabled} onChange={(e) => save({ tools_enabled: e.target.checked })} />{L.toolsOn}</label>
      <div className="row">
        <label className="field"><span>{L.temperature}</span>
          <input type="number" step="0.1" min="0" max="2" defaultValue={settings.temperature ?? ""} onBlur={(e) => save({ temperature: e.target.value === "" ? null : Number(e.target.value) })} />
        </label>
        <label className="field"><span>{L.maxTokens}</span>
          <input type="number" min="64" max="32768" defaultValue={settings.max_tokens ?? ""} onBlur={(e) => save({ max_tokens: e.target.value === "" ? null : Number(e.target.value) })} />
        </label>
        <label className="field"><span>{L.reasoning}</span>
          <select value={settings.reasoning === null ? "" : String(settings.reasoning)} onChange={(e) => save({ reasoning: e.target.value === "" ? null : e.target.value === "true" })}>
            <option value="">{L.rDefault}</option><option value="true">{L.rOn}</option><option value="false">{L.rOff}</option>
          </select>
        </label>
      </div>
    </div>
  );
}

function Providers({ providers, settings, save, reload }: { providers: ProviderInfo[]; settings: Settings; save: (p: Partial<Settings>) => void; reload: () => void }) {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetId, setPresetId] = useState("");
  const [draft, setDraft] = useState({ id: "", base_url: "", model: "", api_key: "" });
  const [tests, setTests] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");

  useEffect(() => { api.get<Preset[]>("/api/presets").then(setPresets); }, []);
  const preset = presets.find((p) => p.id === presetId);

  const add = async () => {
    setErr("");
    try {
      await api.post("/api/providers", {
        preset: presetId, id: draft.id || undefined, base_url: draft.base_url || undefined,
        model: draft.model || undefined, api_key: draft.api_key || undefined,
      });
      setPresetId(""); setDraft({ id: "", base_url: "", model: "", api_key: "" });
      reload();
    } catch (e) { setErr(String((e as Error).message)); }
  };
  const test = async (id: string) => {
    setTests((t) => ({ ...t, [id]: "…" }));
    const r = await api.post<{ ok: boolean; models?: string[]; adapters?: string[]; error?: string }>(`/api/providers/${id}/test`);
    setTests((t) => ({ ...t, [id]: r.ok ? `${L.ok} · ${r.models?.length ?? 0} ${L.models}${r.adapters?.length ? ` · ${r.adapters.length} ${L.adapters}` : ""}` : `✕ ${r.error}` }));
  };
  const patch = async (id: string, body: Record<string, unknown>) => { await api.patch(`/api/providers/${id}`, body); reload(); };
  const remove = async (id: string) => { await api.del(`/api/providers/${id}`); reload(); };

  return (
    <div className="form">
      {providers.map((p) => (
        <div key={p.id} className="card">
          <div className="card-head">
            <b>{p.name}</b>
            <span className="muted small">{p.kind} · {p.base_url}</span>
            {settings.default_provider === p.id ? <span className="badge">{L.default}</span> : <button className="link" onClick={() => save({ default_provider: p.id })}>{L.makeDefault}</button>}
          </div>
          <div className="row">
            <label className="field"><span>{L.model}</span><input defaultValue={p.model} onBlur={(e) => e.target.value !== p.model && patch(p.id, { model: e.target.value })} /></label>
            {!p.local && (
              <label className="field"><span>{L.key} {p.has_key && <em className="muted">({L.keySaved})</em>}</span>
                <input type="password" placeholder="••••••" autoComplete="off" onBlur={(e) => e.target.value && patch(p.id, { api_key: e.target.value })} />
              </label>
            )}
          </div>
          {p.paid && (
            <label className="check warn"><input type="checkbox" checked={p.allow_paid} onChange={(e) => patch(p.id, { allow_paid: e.target.checked })} />{L.allowPaid}<small>{L.paidWarn}</small></label>
          )}
          <div className="card-actions">
            <button className="btn" onClick={() => test(p.id)}>{L.test}</button>
            {tests[p.id] && <span className="small">{tests[p.id]}</span>}
            <div className="spacer" />
            {p.id !== "spike-local" && <button className="icon-btn" onClick={() => remove(p.id)} aria-label={L.remove}><IconTrash size={16} /></button>}
          </div>
        </div>
      ))}
      <div className="card dashed">
        <div className="card-head"><b>{L.add}</b></div>
        <div className="row">
          <label className="field"><span>{L.preset}</span>
            <select value={presetId} onChange={(e) => { setPresetId(e.target.value); const pr = presets.find((x) => x.id === e.target.value); setDraft({ id: "", base_url: pr?.base_url ?? "", model: pr?.example_model ?? "", api_key: "" }); }}>
              <option value="">—</option>
              {presets.filter((x) => x.id !== "spike-local").map((x) => <option key={x.id} value={x.id}>{x.name}{x.paid ? " ($)" : ""}</option>)}
            </select>
          </label>
          {preset && <label className="field"><span>ID</span><input value={draft.id} placeholder={preset.id} onChange={(e) => setDraft({ ...draft, id: e.target.value })} /></label>}
        </div>
        {preset && (
          <>
            <div className="row">
              <label className="field"><span>{L.baseUrl}</span><input value={draft.base_url} onChange={(e) => setDraft({ ...draft, base_url: e.target.value })} /></label>
              <label className="field"><span>{L.model}</span><input value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value })} /></label>
            </div>
            {preset.needs_key && (
              <label className="field"><span>{L.key} {preset.key_url && <a href={preset.key_url} target="_blank" rel="noreferrer">{L.keyLink}</a>}</span>
                <input type="password" autoComplete="off" value={draft.api_key} onChange={(e) => setDraft({ ...draft, api_key: e.target.value })} />
              </label>
            )}
            {preset.paid && <small className="warn-text">{L.paidWarn}</small>}
            <div className="card-actions"><button className="btn primary" onClick={add}>{L.add}</button>{err && <span className="bad small">{err}</span>}</div>
          </>
        )}
      </div>
    </div>
  );
}

function Specialists({ specialists, providers, settings, save }: { specialists: Specialist[]; providers: ProviderInfo[]; settings: Settings; save: (p: Partial<Settings>) => void }) {
  const setBinding = (id: string, provider_id: string) => {
    const next = { ...settings.specialist_bindings };
    if (provider_id) next[id] = { ...(next[id] || {}), provider_id }; else delete next[id];
    save({ specialist_bindings: next });
  };
  const setInstr = (id: string, value: string) => save({ specialist_instructions: { ...settings.specialist_instructions, [id]: value } });
  return (
    <div className="form">
      {specialists.map((s) => (
        <div key={s.id} className="card">
          <div className="card-head">
            <span className={`chip spec-${s.id}`}><SpecMark id={s.id} />{s.name}</span>
            <span className="muted small">{s.domain}</span>
            {s.adapter && <span className={`badge status-${s.adapter_status}`}>{L.adapterStatus}: {s.adapter_status}</span>}
          </div>
          <p className="small muted">{s.description}</p>
          <div className="row">
            <label className="field"><span>{L.bind}</span>
              <select value={settings.specialist_bindings[s.id]?.provider_id ?? ""} onChange={(e) => setBinding(s.id, e.target.value)}>
                <option value="">{L.inherit}</option>
                {providers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
          </div>
          <label className="field"><span>{L.specInstr}</span>
            <textarea rows={2} defaultValue={settings.specialist_instructions[s.id] ?? ""} onBlur={(e) => e.target.value !== (settings.specialist_instructions[s.id] ?? "") && setInstr(s.id, e.target.value)} />
          </label>
        </div>
      ))}
    </div>
  );
}

function Tools({ settings, save }: { settings: Settings; save: (p: Partial<Settings>) => void }) {
  const [tools, setTools] = useState<ToolInfo[]>([]);
  useEffect(() => { api.get<ToolInfo[]>("/api/tools").then(setTools); }, [settings.tool_policies]);
  return (
    <div className="form">
      {tools.map((tool) => (
        <div key={tool.name} className="card row-card">
          <div><code>{tool.name}</code> <span className={`risk risk-${tool.risk}`}>{tool.risk}</span><p className="small muted">{tool.description}</p></div>
          <select value={settings.tool_policies[tool.name] ?? tool.default_policy} onChange={(e) => save({ tool_policies: { ...settings.tool_policies, [tool.name]: e.target.value as "allow" } })} aria-label={L.policy}>
            <option value="allow">{L.allow}</option><option value="ask">{L.ask}</option><option value="deny">{L.deny}</option>
          </select>
        </div>
      ))}
    </div>
  );
}

function Engine({ settings, save }: { settings: Settings; save: (p: Partial<Settings>) => void }) {
  const [sys, setSys] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const load = () => api.get<any>("/api/system").then(setSys);
  useEffect(() => { load(); }, []);
  const rt = settings.local_runtime;
  const act = async (what: "start" | "stop") => {
    setBusy(true); setErr("");
    try { await api.post(`/api/runtime/${what}`); } catch (e) { setErr(String((e as Error).message)); }
    setBusy(false); load();
  };
  if (!sys) return null;
  const hw = sys.hardware;
  return (
    <div className="form">
      <div className="card">
        <div className="card-head"><b>{L.hw}</b></div>
        <p className="small">{hw.cpu_model} · {hw.physical_cores} cores · {hw.total_ram_gb} GB RAM · {hw.os} {hw.arch}{hw.apple_silicon ? " · Metal" : ""}</p>
        <p className="small muted">{L.rec}: {sys.recommendation.quant} · ctx {sys.recommendation.context} · KV {sys.recommendation.kv_cache_type} · {sys.recommendation.threads} threads</p>
        {sys.recommendation.notes.map((n: string) => <p key={n} className="small warn-text">{n}</p>)}
        <p className="small muted">{L.secrets}: {sys.secrets_backend}</p>
      </div>
      <div className="card">
        <div className="card-head"><b>{L.engine}</b><span className={`badge ${sys.runtime.running ? "ok" : ""}`}>{sys.runtime.running ? L.running : L.stoppedS}</span></div>
        <label className="field"><span>{L.modelPath}</span><input defaultValue={rt.model} placeholder="~/.spike/models/Qwen3.5-4B-Q4_K_M.gguf" onBlur={(e) => e.target.value !== rt.model && save({ local_runtime: { ...rt, model: e.target.value } })} /></label>
        <label className="field"><span>{L.ctx}</span><input type="number" defaultValue={rt.context ?? ""} placeholder={String(sys.recommendation.context)} onBlur={(e) => save({ local_runtime: { ...rt, context: e.target.value ? Number(e.target.value) : null } })} /></label>
        {!rt.model && <div className="no-models"><img src="/states/no-models.webp" alt="" width={84} height={89} /><small className="muted">{L.pull}</small></div>}
        {sys.runtime.running && <p className="small muted">RSS {sys.runtime.rss_mb} MB · load {sys.runtime.load_seconds}s · {sys.runtime.adapters.length} {L.adapters}</p>}
        <div className="card-actions">
          <button className="btn primary" disabled={busy} onClick={() => act("start")}>{L.start}</button>
          <button className="btn" disabled={busy || !sys.runtime.running} onClick={() => act("stop")}>{L.stop}</button>
          {err && <span className="bad small">{err}</span>}
        </div>
      </div>
    </div>
  );
}
