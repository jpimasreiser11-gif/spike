import { useState } from "react";
import { api } from "../api";
import { lang, t } from "../i18n";
import type { Blueprint, ProviderInfo, Specialist } from "../types";
import { Forge } from "./Forge";
import "./Research.css";

type Source = { id: string; path: string; sha256: string; pages: string[] };
type Evidence = { source_id: string; path: string; page: number; start: number; end: number; quote: string; claim: string; sha256: string };
type Pair = { left: Evidence; right: Evidence; reason: string };
type Preview = { id: string; sources: Source[]; calls: number; blocked: string | null; estimated_cost: number | null;
  provider: { name: string; id: string; model: string; local: boolean } };
type Result = { kind: "paper" | "contradictions"; sources: Source[]; blueprint?: Blueprint;
  analysis: { status: string; methods?: Evidence[]; equations?: Evidence[]; tables?: Evidence[]; pairs?: Pair[] } };

const R = t.research;
function Reference({ item }: { item: Evidence }) {
  return <div className="research-reference">
    <p><b>{item.path}</b> · {R.page} {item.page} · [{item.start}:{item.end}]</p>
    <blockquote>{item.quote}</blockquote><p>{R.claim}: {item.claim}</p>
    <details><summary>SHA-256</summary><code>{item.sha256}</code></details>
  </div>;
}

/** A local preview followed by explicit guarded analysis. Results remain in this panel until exported. */
export function Research({ conversationId, projectId, projectName, specialists, providers, onRun, onClose }: {
  conversationId?: string | null; projectId?: string; projectName?: string;
  specialists: Specialist[]; providers: ProviderInfo[];
  onRun: (task: string, blueprint: Blueprint, providerId: string | null) => void; onClose: () => void;
}) {
  const [kind, setKind] = useState<"paper" | "contradictions">("paper");
  const [paths, setPaths] = useState("");
  const [providerId, setProviderId] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const reset = () => { setPreview(null); setResult(null); setError(""); };
  const failure = (e: unknown) => { const code = (e as Error).message; setError(R.errors[code] || R.errors.analysis_failed); };
  const prepare = async () => {
    reset(); setBusy(true);
    try { setPreview(await api.post<Preview>("/api/research/preview", { kind, paths: paths.split("\n").map((p) => p.trim()).filter(Boolean),
      project_id: projectId ?? null, provider_id: providerId || null, language: lang })); }
    catch (e) { failure(e); }
    finally { setBusy(false); }
  };
  const analyze = async () => {
    if (!preview || preview.blocked || busy) return;
    const id = preview.id; setPreview(null); setBusy(true); setError("");
    try { setResult(await api.post<Result>("/api/research/analyze", { preview_id: id })); }
    catch (e) { failure(e); }
    finally { setBusy(false); }
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }));
    const a = document.createElement("a"); a.href = url; a.download = "spike-research-evidence.json"; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  if (review && result?.blueprint) return <Forge specialists={specialists} providers={providers} projectId={projectId}
    initialTask={result.blueprint.goal} initialBlueprint={result.blueprint} initialProviderId={providerId || null}
    title={R.paper} intro={R.draft} onBack={() => setReview(false)} onClose={onClose} onRun={onRun} />;

  return <section className="research-panel" aria-label={R.title}>
    <div className="row"><h1>{R.title}</h1><div className="spacer" /><button className="btn" onClick={onClose}>{R.close}</button></div>
    <p className="muted">{R.intro}</p>
    <div className="card"><h2>Notebook</h2><p>{R.notebookHint}</p>
      {conversationId ? <a className="btn" download href={`/api/research/notebooks/${encodeURIComponent(conversationId)}`}>{R.notebook}</a> : <p>{R.noChat}</p>}
    </div>
    <p><b>{R.scope}:</b> {projectName || R.workspace}</p>
    <fieldset disabled={busy} className="research-inputs">
      <div className="row">
        <label className="field"><span>{R.kind}</span><select value={kind} onChange={(e) => { setKind(e.target.value as typeof kind); reset(); }}>
          <option value="paper">{R.paper}</option><option value="contradictions">{R.contradictions}</option>
        </select></label>
        <label className="field"><span>{t.provider}</span><select value={providerId} onChange={(e) => { setProviderId(e.target.value); reset(); }}>
          <option value="">{t.defaultProvider}</option>{providers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select></label>
      </div>
      <label className="field"><span>{R.paths}</span><textarea rows={3} value={paths} onChange={(e) => { setPaths(e.target.value); reset(); }} placeholder={kind === "paper" ? "paper.pdf" : "study-a.txt\nstudy-b.txt"} /></label>
      <p className="small muted">{R.pathHint}</p><button className="btn" disabled={!paths.trim()} onClick={prepare}>{R.preview}</button>
    </fieldset>
    {busy && <p role="status">{R.busy}</p>}{error && <div role="alert" className="error-box">{error}</div>}
    {preview && <div className="card research-preview">
      <p>{R.extractionHint}</p><p><b>{t.provider}: {preview.provider.name}</b> · {preview.provider.local ? R.local : R.external}</p>
      <p>{R.model}: {preview.provider.model}</p>
      <p>{R.cost}: {preview.estimated_cost === null ? R.unknownCost : preview.estimated_cost.toFixed(6)}</p>
      {preview.sources.map((source) => <details key={source.id}><summary>{source.path} · {source.pages.length} {R.page.toLowerCase()}</summary>
        <code>{source.sha256}</code>{source.pages.map((page, i) => <div key={i}><h3>{R.page} {i + 1}</h3><pre>{page}</pre></div>)}
      </details>)}
      <p>{R.sendHint}</p>{preview.blocked && <p role="alert">{R.errors[preview.blocked] || R.errors.provider_blocked}</p>}
      <button className="btn primary" disabled={!!preview.blocked || busy} onClick={analyze}>{R.analyze}</button>
    </div>}
    {result && <div className="research-result">
      <p className="notice">{result.kind === "paper" ? R.draft : R.candidates}</p>
      {result.kind === "paper" ? (["methods", "equations", "tables"] as const).map((key) => <section key={key}>
        <h2>{R[key]}</h2>{result.analysis[key]?.length ? result.analysis[key]!.map((r, i) => <Reference key={i} item={r} />) : <p>{R.empty}</p>}
      </section>) : result.analysis.pairs?.length ? <div className="research-table"><table><thead><tr><th>{R.source} A</th><th>{R.source} B</th><th>{R.reason}</th></tr></thead>
        <tbody>{result.analysis.pairs.map((pair, i) => <tr key={i}><td><Reference item={pair.left} /></td><td><Reference item={pair.right} /></td><td>{pair.reason}</td></tr>)}</tbody>
      </table></div> : <p>{R.empty}</p>}
      <div className="row"><button className="btn" onClick={download}>{R.export}</button>
        {result.blueprint && <button className="btn primary" onClick={() => setReview(true)}>{R.review}</button>}
      </div>
    </div>}
  </section>;
}
