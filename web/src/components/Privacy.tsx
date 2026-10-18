import { useEffect, useState } from "react";
import { api } from "../api";
import { lang } from "../i18n";
import type { CallRow, UsageRow } from "../types";

export const PV = lang === "es"
  ? {
      intro: "Cada llamada que SPIKE hace a un modelo queda anotada aquí, en tu ordenador: a quién, cuántos tokens, si llevaba contenido de tus archivos y si se bloqueó. Los proveedores externos no reciben el contenido de tus archivos salvo que lo permitas en Proveedores.",
      month: "Este mes", call: "llamada", calls: "llamadas", tokens: "tokens", cost: "coste", limit: "tope", estimated: "aprox.",
      log: "Registro de llamadas", showLocal: "Mostrar también las llamadas al modelo local", refresh: "Actualizar", clear: "Vaciar el registro",
      when: "Cuándo", provider: "Proveedor", model: "Modelo", status: "Estado", inOut: "Tokens (entrada / salida)", files: "Archivos",
      sent: "enviados", withheld: "protegidos", empty: "Todavía no hay llamadas registradas.",
      st: { ok: "correcta", error: "error", blocked: "bloqueada", cancelled: "detenida" } as Record<string, string>,
      priceNote: "El coste se calcula con los precios que tú pones en Proveedores; SPIKE no los inventa.",
    }
  : {
      intro: "Every call SPIKE makes to a model is noted here, on your computer: to whom, how many tokens, whether it carried your files' contents and whether it was blocked. External providers do not receive your files' contents unless you allow it in Providers.",
      month: "This month", call: "call", calls: "calls", tokens: "tokens", cost: "cost", limit: "limit", estimated: "approx.",
      log: "Call log", showLocal: "Also show calls to the local model", refresh: "Refresh", clear: "Clear the log",
      when: "When", provider: "Provider", model: "Model", status: "Status", inOut: "Tokens (in / out)", files: "Files",
      sent: "sent", withheld: "protected", empty: "No calls logged yet.",
      st: { ok: "ok", error: "error", blocked: "blocked", cancelled: "stopped" } as Record<string, string>,
      priceNote: "Cost uses the prices you enter in Providers; SPIKE does not make them up.",
    };

const n = (x: number) => x.toLocaleString();

export function Privacy() {
  const [usage, setUsage] = useState<UsageRow[]>([]);
  const [calls, setCalls] = useState<CallRow[]>([]);
  const [local, setLocal] = useState(false);
  const load = () => {
    api.get<UsageRow[]>("/api/usage").then(setUsage).catch(() => {});
    api.get<CallRow[]>(`/api/calls?limit=300&remote=${!local}`).then(setCalls).catch(() => {});
  };
  useEffect(load, [local]);

  return (
    <div className="form">
      <p className="small muted">{PV.intro}</p>
      <div className="card">
        <div className="card-head"><b>{PV.month}</b></div>
        {usage.filter((u) => !u.local || local).map((u) => (
          <div key={u.provider_id} className="usage-row small" data-testid={`usage-${u.provider_id}`}>
            <b>{u.name}</b>
            <span>{n(u.calls)} {u.calls === 1 ? PV.call : PV.calls}</span>
            <span>{n(u.tokens_in + u.tokens_out)} {PV.tokens}{u.limits.monthly_tokens ? ` / ${n(u.limits.monthly_tokens)} ${PV.limit}` : ""}{u.estimated ? ` (${PV.estimated})` : ""}</span>
            {(u.limits.price_in != null || u.limits.price_out != null) && (
              <span>{PV.cost} {u.cost.toFixed(2)}{u.limits.monthly_cost != null ? ` / ${u.limits.monthly_cost.toFixed(2)} ${PV.limit}` : ""}</span>
            )}
          </div>
        ))}
        <small className="muted">{PV.priceNote}</small>
      </div>

      <div className="row">
        <b className="grow">{PV.log}</b>
        <label className="check small"><input type="checkbox" checked={local} onChange={(e) => setLocal(e.target.checked)} />{PV.showLocal}</label>
        <button className="btn small" onClick={load}>{PV.refresh}</button>
        <button className="btn small danger" onClick={() => api.del("/api/calls").then(load)}>{PV.clear}</button>
      </div>
      {calls.length === 0 ? <p className="small muted">{PV.empty}</p> : (
        <div className="table-wrap">
          <table className="calls" aria-label={PV.log}>
            <thead><tr><th>{PV.when}</th><th>{PV.provider}</th><th>{PV.model}</th><th>{PV.status}</th><th>{PV.inOut}</th><th>{PV.files}</th></tr></thead>
            <tbody>
              {calls.map((c) => (
                <tr key={c.id} className={`call-${c.status}`} title={c.detail || undefined}>
                  <td>{new Date(c.ts * 1000).toLocaleString()}</td>
                  <td>{c.provider}</td>
                  <td><code>{c.model}</code></td>
                  <td>{PV.st[c.status] ?? c.status}</td>
                  <td>{c.estimated ? "≈ " : ""}{n(c.tokens_in)} / {n(c.tokens_out)}{c.cost != null ? ` · ${c.cost.toFixed(4)}` : ""}</td>
                  <td>{c.files_withheld ? `${c.files_withheld} ${PV.withheld}` : c.files_sent ? `${c.files_sent} ${PV.sent}` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
