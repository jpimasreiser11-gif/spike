import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { projectError, t } from "../i18n";
import { resizeImage } from "../media";
import type { Project } from "../types";
import { ArtifactContext, artifactDocument } from "./Artifact";
import "./ReverseStudio.css";

const R = t.reverse;
type Source = "image" | "url" | "file";
type Provider = { id: string; name: string; local: boolean; vision: boolean; receives_files: boolean };
type Status = { browser: boolean; providers: Provider[]; default_provider: string; statement: string };
type Quote = {
  id: string; sends: "image" | "structure"; egress: boolean; blocked: string | null; estimated_cost: number | null;
  provider: { id: string; name: string; model: string; local: boolean };
};
type Fidelity = { measured: true; score: number; width: number; height: number; metric: string; against: "image" | "page" }
  | { measured: false; reason: string };
type Result = {
  html: string; title: string; filename: string; path: string; project_id: string | null; fidelity: Fidelity;
  authorization: { at: string; statement: string }; removed: { scripts: number; links: number; images_and_graphics: number };
  names_removed: string[]; size: { width: number; height: number };
};

/** Settings › Design: turn a reference you own (a screenshot, or a page on this computer) into one editable HTML/CSS
 * file. Nothing is sent or opened until the ownership box is ticked, and an image only leaves this computer after
 * the user has seen where it goes and clicked send. */
export function ReverseStudio({ onClose }: { onClose?: () => void }) {
  const openArtifact = useContext(ArtifactContext);
  const [status, setStatus] = useState<Status | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [source, setSource] = useState<Source>("url");
  const [image, setImage] = useState(""), [imageName, setImageName] = useState("");
  const [url, setUrl] = useState("http://localhost:5173/"), [path, setPath] = useState("");
  const [projectId, setProjectId] = useState(""), [providerId, setProviderId] = useState("");
  const [authorized, setAuthorized] = useState(false);
  const [ownText, setOwnText] = useState(""), [avoid, setAvoid] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [quote, setQuote] = useState<Quote | null>(null);
  const [result, setResult] = useState<Result | null>(null), [code, setCode] = useState("");
  const alive = useRef(true), input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    alive.current = true;
    api.get<Status>("/api/reverse").then((s) => { if (alive.current) { setStatus(s); setProviderId(s.default_provider); } }).catch(() => {});
    api.get<Project[]>("/api/projects").then((p) => { if (alive.current) setProjects(p); }).catch(() => {});
    return () => { alive.current = false; };
  }, []);

  const provider = status?.providers.find((p) => p.id === providerId);
  const needsVision = source === "image" && !!provider && !provider.vision;
  const hasReference = source === "image" ? !!image : source === "url" ? !!url.trim() : !!path.trim();
  // changing what is being used revokes the confirmation: it covers one reference
  const change = (fn: () => void) => { fn(); setAuthorized(false); setQuote(null); };

  const body = () => ({
    authorized: true, source, provider_id: providerId || undefined, project_id: projectId || undefined,
    ...(source === "image" ? { image } : source === "url" ? { url: url.trim() } : { path: path.trim() }),
    own_text: ownText, avoid: avoid.split(",").map((s) => s.trim()).filter(Boolean),
  });
  const fail = (e: unknown) => { if (alive.current) setError(e instanceof ApiError ? e.message : R.failed); };

  async function run() {
    if (busy) return;
    setBusy(true); setError(""); setNotice(""); setResult(null); setQuote(null);
    try {
      const q = await api.post<Quote>("/api/reverse/preview", body());
      if (!alive.current) return;
      if (q.blocked) { setError(`${R.blocked}: ${projectError(q.blocked)}`); return; }
      if (q.egress) { setQuote(q); return; } // something would leave this computer: ask first
      await finish(q);
    } catch (e) { fail(e); } finally { if (alive.current) setBusy(false); }
  }
  async function finish(q: Quote) {
    setBusy(true); setError("");
    try {
      const r = await api.post<Result>("/api/reverse/generate", { preview_id: q.id });
      if (alive.current) { setResult(r); setCode(r.html); setQuote(null); setAuthorized(false); }
    } catch (e) { fail(e); setQuote(null); } finally { if (alive.current) setBusy(false); }
  }
  async function saveEdits() {
    if (!result) return;
    setError(""); setNotice("");
    try {
      await api.put("/api/reverse/file", { project_id: result.project_id || undefined, path: result.path, html: code });
      if (alive.current) { setResult({ ...result, html: code }); setNotice(R.savedOk); }
    } catch (e) { fail(e); }
  }
  async function choose(file?: File) {
    if (!file) return;
    setError("");
    try { const data = await resizeImage(file); change(() => { setImage(data); setImageName(file.name); }); }
    catch (e) { setError((e as Error).message); }
    if (input.current) input.current.value = "";
  }
  const open = () => {
    if (!result) return;
    openArtifact?.({ title: result.title, html: code, filename: result.filename });
    onClose?.(); // the artifacts panel sits behind the settings window
  };
  const frame = useMemo(() => (result ? artifactDocument(code) : ""), [result, code]);
  const cost = quote ? (quote.estimated_cost == null ? R.noPrice : R.cost.replace("{cost}", quote.estimated_cost.toFixed(4))) : "";
  const fidelity = result?.fidelity;

  return (
    <section className="form reverse-studio" aria-labelledby="reverse-title" data-testid="reverse-studio">
      <h3 id="reverse-title">{R.title}</h3>
      <p className="small muted">{R.intro}</p>
      <fieldset className="reverse-source">
        <legend>{R.source}</legend>
        {(["image", "url", "file"] as Source[]).map((k) => (
          <label key={k} className="check"><input type="radio" name="reverse-source" checked={source === k} disabled={busy}
            onChange={() => change(() => setSource(k))} />{R[k]}</label>
        ))}
      </fieldset>
      {source === "image" && (
        <div className="row end">
          <button type="button" className="btn" disabled={busy} onClick={() => input.current?.click()}>{R.pickImage}</button>
          <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" hidden data-testid="reverse-image"
            onChange={(e) => void choose(e.target.files?.[0])} />
          <span className="small muted">{imageName || R.noImage}</span>
          {image && <img className="reverse-thumb" src={image} alt="" width={96} height={64} />}
        </div>
      )}
      {source === "url" && (
        <label className="field">{R.urlLabel}
          <input name="reverse-url" value={url} disabled={busy} onChange={(e) => change(() => setUrl(e.target.value))} placeholder="http://localhost:5173/" />
        </label>
      )}
      {source === "file" && (
        <label className="field">{R.pathLabel}
          <input name="reverse-path" value={path} disabled={busy} onChange={(e) => change(() => setPath(e.target.value))} placeholder="index.html" />
        </label>
      )}
      <div className="row">
        <label className="field">{R.provider}
          <select value={providerId} disabled={busy} onChange={(e) => { setProviderId(e.target.value); setQuote(null); }} aria-label={R.provider}>
            {status?.providers.map((p) => (
              <option key={p.id} value={p.id}>{p.name} · {p.local ? R.local : R.remote} · {p.vision ? R.vision : R.noVision}</option>
            ))}
          </select>
        </label>
        <label className="field">{R.saveIn}
          <select value={projectId} disabled={busy} onChange={(e) => setProjectId(e.target.value)} aria-label={R.saveIn}>
            <option value="">{R.workspace}</option>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
      </div>
      {needsVision && <div className="error-box" role="alert" data-testid="reverse-needs-vision">{R.needsVision}</div>}
      {status && !status.browser && <small className="muted">{R.needsBrowser}</small>}
      <label className="field">{R.ownText}
        <textarea rows={3} value={ownText} disabled={busy} onChange={(e) => setOwnText(e.target.value)} />
      </label>
      <label className="field">{R.avoid}
        <input value={avoid} disabled={busy} onChange={(e) => setAvoid(e.target.value)} />
      </label>
      <label className="check">
        <input type="checkbox" name="reverse-authorized" checked={authorized} disabled={busy} onChange={(e) => setAuthorized(e.target.checked)} />
        {R.authorize}<small className="hint">{R.authorizeHint}</small>
      </label>
      <div className="row end">
        <button type="button" className="btn primary" data-testid="reverse-generate"
          disabled={busy || !authorized || !hasReference || needsVision || !!quote} onClick={() => void run()}>
          {busy ? R.working : R.generate}
        </button>
      </div>
      {error && <div className="error-box" role="alert">{error}</div>}
      {notice && <div className="flash-box" role="status">{notice}</div>}
      {quote && (
        <div className="card reverse-confirm" role="group" aria-label={R.confirmTitle} data-testid="reverse-confirm">
          <b>{R.confirmTitle}</b>
          <p>{(quote.sends === "image" ? R.sendsImage : R.sendsStructure).replace("{provider}", `${quote.provider.name} (${quote.provider.model})`)}</p>
          <small className="muted">{cost}</small>
          <div className="card-actions">
            <button type="button" className="btn primary" data-testid="reverse-send" disabled={busy} onClick={() => void finish(quote)}>{R.send}</button>
            <button type="button" className="btn" disabled={busy} onClick={() => setQuote(null)}>{R.cancel}</button>
          </div>
        </div>
      )}
      {result && fidelity && (
        <div className="card reverse-result" data-testid="reverse-result">
          <div className="card-head"><b>{R.result}</b><span className="badge">{result.size.width}×{result.size.height}</span></div>
          <p className="small">{R.savedAt} <code>{result.path}</code></p>
          <p className="small" data-testid="reverse-score">
            {fidelity.measured
              ? <>{R.score}: <b>{fidelity.score.toFixed(4)}</b> ({fidelity.against === "image" ? R.scoreAgainstImage : R.scoreAgainstPage}, {R.size} {fidelity.width}×{fidelity.height})</>
              : <>{R.notMeasured}: {projectError(fidelity.reason)}</>}
          </p>
          {fidelity.measured && <small className="muted">{R.scoreHint}</small>}
          <small className="muted">{R.authorization}: {result.authorization.at}</small>
          <small className="muted">{R.removed.replace("{n}", String(result.removed.images_and_graphics)).replace("{s}", String(result.removed.scripts)).replace("{l}", String(result.removed.links))}
            {result.names_removed.length > 0 && ` ${R.names} ${result.names_removed.join(", ")}.`}</small>
          <iframe className="design-frame" title={result.title} sandbox="allow-scripts" srcDoc={frame} referrerPolicy="no-referrer" />
          <label className="field">{R.editTitle}
            <textarea className="reverse-code" rows={10} spellCheck={false} value={code} onChange={(e) => setCode(e.target.value)} data-testid="reverse-code" />
          </label>
          <div className="card-actions">
            <button type="button" className="btn" disabled={code === result.html} onClick={() => void saveEdits()}>{R.save}</button>
            <button type="button" className="btn primary" onClick={open}>{R.openPanel}</button>
          </div>
        </div>
      )}
    </section>
  );
}
