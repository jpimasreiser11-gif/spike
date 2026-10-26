import { useEffect, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";
import type { ProviderInfo, Specialist } from "../types";
import "./Lab.css";

type Target = { specialist: string; provider_id: string | null };
type Identity = Target & { model: string; adapter: string | null };
type Quote = { id: string; calls: number; estimated_cost: number | null; blocked: boolean; targets: Identity[] };
type Row = Identity & {
  output?: string; status: "ok" | "failed" | "observed" | "not_observed" | "untested";
  capability?: "tools" | "json" | "vision" | "streaming" | "context"; context_tokens_tested?: number;
  latency_ms?: number; tokens_in?: number; tokens_out?: number; estimated_tokens?: boolean;
  cost?: number | null; score?: number | null; case?: number; prompt?: string;
};
type Run = { id: string; created: number; kind: "compare" | "probe"; rows: Row[] };
const L = t.lab;

/** A preview never makes a provider call. Its single-use quote is executed only by the second explicit click. */
export function Lab({ specialists, providers, onClose }: {
  specialists: Specialist[]; providers: ProviderInfo[]; onClose: () => void;
}) {
  const [targets, setTargets] = useState<Target[]>([{ specialist: "core", provider_id: null }]);
  const [prompt, setPrompt] = useState("");
  const [cases, setCases] = useState("");
  const [quote, setQuote] = useState<Quote | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState<Run | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api.get<Run[]>("/api/lab/runs").then(setRuns).catch(() => setError(L.failed)); }, []);
  const change = (fn: () => void) => { setQuote(null); setError(""); fn(); };
  const preview = async (kind: "compare" | "probe") => {
    setQuote(null); setError("");
    let parsed: unknown = [];
    try {
      parsed = kind === "compare" && cases.trim() ? JSON.parse(cases) : [];
      if (!Array.isArray(parsed)) throw new Error();
    } catch { setError(L.invalid); return; }
    setBusy(true);
    try {
      setQuote(await api.post<Quote>("/api/lab/preview", {
        kind, prompt, cases: parsed, targets: kind === "probe" ? targets.slice(0, 1) : targets,
      }));
    } catch { setError(L.failed); } finally { setBusy(false); }
  };
  const execute = async () => {
    if (!quote || busy) return;
    const id = quote.id; setQuote(null); setBusy(true); setError("");
    try {
      const run = await api.post<Run>("/api/lab/execute", { quote_id: id });
      setSelected(run); setRuns((old) => [run, ...old].slice(0, 50));
    } catch { setError(L.failed); } finally { setBusy(false); }
  };
  const name = (row: Identity) => `${specialists.find((s) => s.id === row.specialist)?.name ?? row.specialist} · ${providers.find((p) => p.id === row.provider_id)?.name ?? row.provider_id} · ${row.model} · ${row.adapter ? `${L.adapter}: ${row.adapter}` : L.profile}`;
  return <section className="forge lab" aria-label={L.title}>
    <div className="forge-head"><h1>{L.title}</h1><button className="btn" disabled={busy} onClick={onClose}>{L.close}</button></div>
    <p className="muted">{L.intro}</p>
    <fieldset disabled={busy} className="lab-fields">
      <label className="field"><span>{L.prompt}</span><textarea aria-label={L.prompt} value={prompt} maxLength={8000} rows={3} onChange={(e) => change(() => setPrompt(e.target.value))} /></label>
      <label className="field"><span>{L.cases}</span><textarea aria-label={L.cases} value={cases} rows={3} onChange={(e) => change(() => setCases(e.target.value))} /></label>
      <p className="small muted">{L.casesHint}</p>
      {targets.map((target, index) => <div className="row" key={index}>
        <label className="field"><span>{L.specialist}</span><select aria-label={`${L.specialist} ${index + 1}`} value={target.specialist} onChange={(e) => change(() => setTargets(targets.map((r, i) => i === index ? { ...r, specialist: e.target.value } : r)))}>
          {specialists.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select></label>
        <label className="field"><span>{L.provider}</span><select aria-label={`${L.provider} ${index + 1}`} value={target.provider_id ?? ""} onChange={(e) => change(() => setTargets(targets.map((r, i) => i === index ? { ...r, provider_id: e.target.value || null } : r)))}>
          <option value="">{L.binding}</option>{providers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select></label>
        {targets.length > 1 && <button className="btn" onClick={() => change(() => setTargets(targets.filter((_, i) => i !== index)))}>{L.remove}</button>}
      </div>)}
      <div className="row">
        <button className="btn" disabled={targets.length >= 8} onClick={() => change(() => setTargets([...targets, { specialist: "core", provider_id: null }]))}>{L.add}</button>
        <button className="btn" disabled={!prompt.trim() && !cases.trim()} onClick={() => preview("compare")}>{L.comparePreview}</button>
        <button className="btn" onClick={() => preview("probe")}>{L.probePreview}</button>
      </div>
    </fieldset>
    <p className="small muted">{L.probeHint}</p>
    {error && <p className="error-box" role="alert">{error}</p>}
    {busy && <p role="status">{L.busy}</p>}
    {quote && <div className="lab-quote" role="status">
      <p>{L.calls}: {quote.calls} · {L.cost}: {quote.estimated_cost == null ? L.noPrice : `≈ ${quote.estimated_cost.toFixed(6)}`}</p>
      <p className="small muted">{L.estimateHint}</p>
      {quote.targets.map((r, i) => <p key={i}>{name(r)}</p>)}
      {quote.blocked && <p>{L.blocked}</p>}
      <button className="btn primary" disabled={quote.blocked || busy} onClick={execute}>{L.execute}</button>
    </div>}
    {selected && <div className="lab-results">
      <a className="btn" href={`/api/lab/runs/${selected.id}/export`} download>{L.export}</a>
      <div className="lab-table"><table><thead><tr>
        {[L.specialist, L.result, L.latency, L.tokens, L.score, L.cost].map((s) => <th key={s}>{s}</th>)}
      </tr></thead><tbody>{selected.rows.map((r, i) => <tr key={i}>
        <td>{name(r)}{r.case != null && <p>#{r.case}</p>}</td>
        <td>{r.capability && <strong>{L[r.capability]}: </strong>}{L[r.status]}
          {r.context_tokens_tested != null && <p>{L.context}: {r.context_tokens_tested}</p>}
          {r.prompt && <details><summary>{L.prompt}</summary><pre>{r.prompt}</pre></details>}
          {r.output && <pre>{r.output}</pre>}</td>
        <td>{r.latency_ms ?? "—"}</td><td>{r.tokens_in ?? "—"} / {r.tokens_out ?? "—"}{r.estimated_tokens && ` (${L.estimated})`}</td>
        <td>{r.score ?? "—"}</td><td>{r.cost == null ? L.noPrice : `≈ ${r.cost.toFixed(6)}`}</td>
      </tr>)}</tbody></table></div>
    </div>}
    <h2>{L.history}</h2>
    <div className="row">{runs.map((run) => <button className="btn" key={run.id} onClick={() => setSelected(run)}>
      {new Date(run.created * 1000).toLocaleString()} · {run.kind === "probe" ? L.probePreview : L.comparePreview}
    </button>)}</div>
  </section>;
}
