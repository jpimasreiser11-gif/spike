import { useEffect, useState } from "react";
import { api } from "../api";
import { lang } from "../i18n";
import type { ConnectorInfo } from "../types";
import { IconTrash } from "./Icons";

const C = lang === "es"
  ? {
      intro: "Los conectores son servidores MCP. Sus herramientas pasan por los mismos permisos que las de SPIKE: por defecto, SPIKE te pregunta antes de cada uso.",
      enable: "Activar", disable: "Desactivar", retry: "Reintentar", willRun: "Se ejecutará en tu equipo:", willConnect: "SPIKE se conectará a:", confirm: "Activar",
      cancel: "Cancelar", paid: "de pago", license: "Licencia", source: "Código", requires: "Requiere", policy: "Permiso para sus herramientas", allow: "Permitir", ask: "Preguntar",
      deny: "Bloquear", saveSecrets: "Guardar", saved: "guardada", tools: "herramientas", running: "Activo", error: "Error", stopped: "Parado", starting: "Iniciando…",
      custom: "Añadir un servidor MCP propio", id: "Identificador (minúsculas)", name: "Nombre", transport: "Transporte", command: "Comando", args: "Argumentos (uno por línea)",
      url: "URL", add: "Añadir", remove: "Eliminar", getKey: "Obtener",
    }
  : {
      intro: "Connectors are MCP servers. Their tools go through the same permissions as SPIKE's own: by default SPIKE asks you before each use.",
      enable: "Enable", disable: "Disable", retry: "Retry", willRun: "This will run on your computer:", willConnect: "SPIKE will connect to:", confirm: "Enable",
      cancel: "Cancel", paid: "paid", license: "License", source: "Source", requires: "Requires", policy: "Permission for its tools", allow: "Allow", ask: "Ask",
      deny: "Block", saveSecrets: "Save", saved: "saved", tools: "tools", running: "Running", error: "Error", stopped: "Stopped", starting: "Starting…",
      custom: "Add your own MCP server", id: "Id (lowercase)", name: "Name", transport: "Transport", command: "Command", args: "Arguments (one per line)",
      url: "URL", add: "Add", remove: "Remove", getKey: "Get",
    };

export function Connectors() {
  const [list, setList] = useState<ConnectorInfo[]>([]);
  const [error, setError] = useState("");
  const load = () => api.get<ConnectorInfo[]>("/api/connectors").then(setList).catch((e) => setError(String(e.message)));
  useEffect(() => { load(); }, []);
  const replace = (c: ConnectorInfo) => setList((prev) => prev.map((x) => (x.id === c.id ? c : x)));
  return (
    <div className="form">
      <p className="small muted">{C.intro}</p>
      {error && <div className="error-box" role="alert">{error}</div>}
      {list.map((c) => <ConnectorCard key={c.id} c={c} onChange={replace} onRemoved={load} />)}
      <CustomConnector onAdded={load} />
    </div>
  );
}

function ConnectorCard({ c, onChange, onRemoved }: { c: ConnectorInfo; onChange: (c: ConnectorInfo) => void; onRemoved: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");
  const put = async (body: Record<string, unknown>) => {
    setBusy(true); setErr("");
    try { onChange(await api.put<ConnectorInfo>(`/api/connectors/${c.id}`, body)); } catch (e) { setErr(String((e as Error).message)); }
    setBusy(false);
  };
  const status = busy ? "starting" : c.status;
  return (
    <div className="card connector" data-connector={c.id}>
      <div className="card-head">
        <b>{c.name}</b>
        <span className={`badge ${status === "running" ? "ok" : ""}`}>{C[status]}</span>
        {c.paid && <span className="badge warn">{C.paid}</span>}
        <div className="spacer" />
        {c.enabled
          ? <><button className="btn" disabled={busy} onClick={() => put({ enabled: true })}>{C.retry}</button>
              <button className="btn" disabled={busy} onClick={() => put({ enabled: false })}>{C.disable}</button></>
          : <button className="btn primary" disabled={busy} onClick={() => setConfirming(true)}>{C.enable}</button>}
      </div>
      {c.description && <p className="small">{c.description}</p>}
      <p className="small muted">{C.license}: {c.license || "—"} · <a href={c.source} target="_blank" rel="noreferrer">{C.source}</a>{c.requires && <> · {C.requires}: {c.requires}</>}</p>
      {c.note && <p className="small warn-text">{c.note}</p>}
      {confirming && (
        <div className="confirm-box">
          <p className="small">{c.transport === "http" ? C.willConnect : C.willRun}</p>
          <code className="cmd">{c.preview}</code>
          <div className="row end"><div className="spacer" />
            <button className="btn" onClick={() => setConfirming(false)}>{C.cancel}</button>
            <button className="btn primary" onClick={() => { setConfirming(false); put({ enabled: true, secrets: Object.keys(secrets).length ? secrets : undefined }); }}>{C.confirm}</button>
          </div>
        </div>
      )}
      {c.secrets.length > 0 && (
        <div className="row">
          {c.secrets.map((s) => (
            <label key={s.name} className="field"><span>{s.label || s.name} {c.secrets_set[s.name] && <em className="muted">({C.saved})</em>} {s.url && <a href={s.url} target="_blank" rel="noreferrer">{C.getKey}</a>}</span>
              <input type="password" autoComplete="off" value={secrets[s.name] ?? ""} onChange={(e) => setSecrets({ ...secrets, [s.name]: e.target.value })} />
            </label>
          ))}
          <button className="btn align-end" disabled={busy || !Object.values(secrets).some(Boolean)} onClick={() => { put({ secrets }); setSecrets({}); }}>{C.saveSecrets}</button>
        </div>
      )}
      <label className="field inline"><span>{C.policy}</span>
        <select value={c.policy} onChange={(e) => put({ policy: e.target.value })}>
          <option value="allow">{C.allow}</option><option value="ask">{C.ask}</option><option value="deny">{C.deny}</option>
        </select>
      </label>
      {(err || c.error) && <div className="error-box small-pre" role="alert">{err || c.error}</div>}
      {c.tools.length > 0 && <p className="small muted">{c.tools.length} {C.tools}: {c.tools.map((t) => t.remote_name).join(", ")}</p>}
      {c.custom && <div className="row end"><div className="spacer" /><button className="btn danger" onClick={() => api.del(`/api/connectors/${c.id}`).then(onRemoved)}><IconTrash size={14} /> {C.remove}</button></div>}
    </div>
  );
}

function CustomConnector({ onAdded }: { onAdded: () => void }) {
  const [f, setF] = useState({ id: "", name: "", transport: "stdio", command: "", args: "", url: "" });
  const [err, setErr] = useState("");
  const add = async (e: React.FormEvent) => {
    e.preventDefault(); setErr("");
    try {
      await api.post("/api/connectors", { ...f, args: f.args.split("\n").map((a) => a.trim()).filter(Boolean) });
      setF({ id: "", name: "", transport: "stdio", command: "", args: "", url: "" });
      onAdded();
    } catch (e2) { setErr(String((e2 as Error).message)); }
  };
  return (
    <form className="card" onSubmit={add}>
      <div className="card-head"><b>{C.custom}</b></div>
      <div className="row">
        <label className="field"><span>{C.id}</span><input required pattern="[a-z0-9][a-z0-9-]{0,30}" value={f.id} onChange={(e) => setF({ ...f, id: e.target.value })} /></label>
        <label className="field"><span>{C.name}</span><input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
        <label className="field"><span>{C.transport}</span>
          <select value={f.transport} onChange={(e) => setF({ ...f, transport: e.target.value })}><option value="stdio">stdio</option><option value="http">Streamable HTTP</option></select>
        </label>
      </div>
      {f.transport === "stdio" ? (
        <div className="row">
          <label className="field"><span>{C.command}</span><input required value={f.command} onChange={(e) => setF({ ...f, command: e.target.value })} placeholder="npx" /></label>
          <label className="field"><span>{C.args}</span><textarea rows={2} value={f.args} onChange={(e) => setF({ ...f, args: e.target.value })} /></label>
        </div>
      ) : (
        <label className="field"><span>{C.url}</span><input required type="url" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} placeholder="https://…/mcp" /></label>
      )}
      {err && <div className="error-box" role="alert">{err}</div>}
      <div className="row end"><div className="spacer" /><button className="btn primary" type="submit">{C.add}</button></div>
    </form>
  );
}
