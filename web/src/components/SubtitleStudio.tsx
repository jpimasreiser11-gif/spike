import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { projectError, t } from "../i18n";
import "./SubtitleStudio.css";

type Cue = { start_ms: number; end_ms: number; text: string };
type Status = { enabled: boolean; whisper: boolean; ffmpeg: boolean; ffprobe: boolean; max_seconds: number };
const S = t.subtitles;

/** A plain-text subtitle editor. Local program execution is opt-in; editing and export need no model. */
export function SubtitleStudio({ projectId, projectName, onClose }: {
  projectId?: string; projectName?: string; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null), alive = useRef(true);
  const urls = useRef<string[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [path, setPath] = useState("");
  const [approved, setApproved] = useState(false), [renderApproved, setRenderApproved] = useState(false);
  const [cues, setCues] = useState<Cue[]>([]), [undo, setUndo] = useState<Cue[][]>([]);
  const [page, setPage] = useState(0), [shift, setShift] = useState(0);
  const [dirty, setDirty] = useState(false), [leaving, setLeaving] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  useEffect(() => {
    alive.current = true;
    const previous = document.activeElement as HTMLElement | null;
    const el = dialog.current!; el.showModal();
    api.get<Status>("/api/subtitles").then((s) => { if (alive.current) setStatus(s); }).catch(() => { if (alive.current) setError(S.failed); });
    return () => { alive.current = false; el.close(); if (previous?.isConnected) previous.focus(); urls.current.forEach((url) => URL.revokeObjectURL(url)); };
  }, []);
  useEffect(() => {
    if (!dirty && !busy) return;
    const preventLoss = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", preventLoss);
    return () => window.removeEventListener("beforeunload", preventLoss);
  }, [dirty, busy]);
  function close() { if (dirty || busy) setLeaving(true); else onClose(); }
  function change(next: Cue[]) {
    setUndo((old) => [...old.slice(-19), cues]); setCues(next); setDirty(true); setRenderApproved(false); setNotice("");
    setPage((p) => Math.min(p, Math.max(0, Math.ceil(next.length / 25) - 1)));
  }
  async function action(fn: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try { await fn(); } catch (e) { if (alive.current) setError(e instanceof ApiError ? e.message : S.failed); }
    finally { if (alive.current) setBusy(false); }
  }
  async function importFile(file?: File) {
    if (!file) return;
    await action(async () => {
      if (file.size > 1_000_000 || !/\.(srt|vtt)$/i.test(file.name)) throw new Error();
      const response = await api.post<{ cues: Cue[] }>("/api/subtitles/import", { text: await file.text(), format: file.name.toLowerCase().endsWith(".vtt") ? "vtt" : "srt" });
      if (alive.current) { change(response.cues); setPage(0); }
    });
  }
  async function edit(actionName: string, index = 0) {
    await action(async () => {
      const response = await api.post<{ cues: Cue[] }>("/api/subtitles/edit", { cues, action: actionName, index, delta_ms: shift });
      if (alive.current) change(response.cues);
    });
  }
  async function download(endpoint: string, body: object, filename: string) {
    const response = await fetch(`/api/subtitles/${endpoint}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new ApiError(response.status, typeof data.detail === "string" ? data.detail : S.failed);
    }
    const blob = await response.blob();
    if (!alive.current) return;
    const url = URL.createObjectURL(blob); urls.current.push(url);
    while (urls.current.length > 2) URL.revokeObjectURL(urls.current.shift()!);
    const a = document.createElement("a"); a.href = url; a.download = filename; document.body.append(a); a.click(); a.remove();
    setNotice(S.downloaded);
    if (endpoint === "export") setDirty(false);
  }
  const valid = cues.length > 0 && cues.every((c, i) => Number.isInteger(c.start_ms) && Number.isInteger(c.end_ms)
    && c.start_ms >= (i ? cues[i - 1].end_ms : 0) && c.end_ms > c.start_ms && c.end_ms <= 86_400_000
    && c.text.trim() && c.text.length <= 2000 && !c.text.includes("\n\n"));
  const video = /\.(mp4|mov|mkv|webm)$/i.test(path);
  return (
    <dialog ref={dialog} className="subtitle-studio" aria-labelledby="subtitle-heading"
      onCancel={(e) => { e.preventDefault(); close(); }}>
      <header><div><span className="subtitle-eyebrow">SPIKE Motion · {projectName ?? S.workspace}</span><h2 id="subtitle-heading">{S.title}</h2></div>
        <button className="btn" data-testid="subtitle-close" onClick={close}>{S.close}</button></header>
      <p className="subtitle-note">{S.intro}</p>
      {leaving && <div role="alert" className="notice"><p>{busy ? S.runningClose : S.unsaved}</p>
        <button className="btn" onClick={() => setLeaving(false)}>{S.keep}</button>{" "}<button className="btn" onClick={onClose}>{S.discard}</button></div>}
      <div className="subtitle-source-grid">
        <section aria-label={S.importTitle}><h3>{S.importTitle}</h3><p>{S.importHint}</p>
          <label className="btn">{S.importFile}<input name="subtitle-import" type="file" accept=".srt,.vtt,text/vtt,application/x-subrip" disabled={busy}
            onChange={(e) => { void importFile(e.target.files?.[0]); e.target.value = ""; }} /></label>
        </section>
        <section aria-label={S.localTitle}><h3>{S.localTitle}</h3><p>{S.localHint}</p>
          <label>{S.path}<input name="media-path" placeholder="media/entrevista.mp4" value={path} disabled={busy}
            onChange={(e) => { setPath(e.target.value); setApproved(false); setRenderApproved(false); }} /></label>
          <p className="subtitle-tools">whisper.cpp: {status?.whisper ? S.available : S.missing} · ffmpeg: {status?.ffmpeg ? S.available : S.missing} · ffprobe: {status?.ffprobe ? S.available : S.missing}</p>
          {status && !status.enabled && <p>{S.configure}</p>}
          <label className="subtitle-check"><input name="approve-media" type="checkbox" checked={approved} disabled={busy}
            onChange={(e) => setApproved(e.target.checked)} />{S.approve}</label>
          <button className="btn" data-testid="subtitle-transcribe" disabled={busy || !path.trim() || !approved || !status?.whisper || !status.enabled}
            onClick={() => void action(async () => {
              const result = await api.post<{ cues: Cue[] }>("/api/subtitles/transcribe", { path, project_id: projectId, approved: true });
              if (alive.current) { change(result.cues); setPage(0); setApproved(false); }
            })}>{S.transcribe}</button>
        </section>
      </div>
      <p role="status" aria-live="polite">{busy ? S.working : notice || (cues.length ? `${cues.length} ${S.cues}` : S.empty)}</p>
      {error && <p className="notice error" role="alert">{projectError(error)}</p>}
      {cues.length > 0 && <>
        <div className="subtitle-toolbar"><label>{S.shift}<input type="number" value={shift} step={100} disabled={busy} onChange={(e) => setShift(Number(e.target.value))} /></label>
          <button className="btn" disabled={busy || !valid || !Number.isInteger(shift)} onClick={() => void edit("shift")}>{S.apply}</button>
          <button className="btn" disabled={busy || !undo.length} onClick={() => { setCues(undo[undo.length - 1]); setUndo(undo.slice(0, -1)); setDirty(true); setRenderApproved(false); setPage(0); }}>{S.undo}</button>
          <span>{S.splitHint}</span></div>
        {!valid && <p role="alert" className="notice error">{S.invalid}</p>}
        <ol className="subtitle-cues" start={page * 25 + 1}>{cues.slice(page * 25, page * 25 + 25).map((cue, offset) => {
          const index = page * 25 + offset;
          const update = (value: Partial<Cue>) => change(cues.map((c, i) => i === index ? { ...c, ...value } : c));
          return <li key={index} className="subtitle-cue">
            <span className="subtitle-number">{index + 1}</span><div className="subtitle-times">
              <label>{S.start} {index + 1}<input aria-label={`${S.start} ${index + 1}`} type="number" step={100} value={cue.start_ms} disabled={busy} onChange={(e) => update({ start_ms: Number(e.target.value) })} /></label>
              <label>{S.end} {index + 1}<input aria-label={`${S.end} ${index + 1}`} type="number" step={100} value={cue.end_ms} disabled={busy} onChange={(e) => update({ end_ms: Number(e.target.value) })} /></label>
            </div><label className="subtitle-text">{S.text} {index + 1}<textarea aria-label={`${S.text} ${index + 1}`} rows={2} value={cue.text} maxLength={2000} disabled={busy} onChange={(e) => update({ text: e.target.value })} /></label>
            <div className="subtitle-cue-actions"><button className="btn" aria-label={`${S.split} ${index + 1}`} disabled={busy || !valid || cue.text.trim().split(/\s+/).length < 2 || cue.end_ms - cue.start_ms < 2} onClick={() => void edit("split", index)}>{S.split}</button>
              <button className="btn" aria-label={`${S.merge} ${index + 1}`} disabled={busy || !valid || index === cues.length - 1} onClick={() => void edit("merge", index)}>{S.merge}</button></div>
          </li>;
        })}</ol>
        {cues.length > 25 && <nav className="subtitle-toolbar" aria-label={S.pages}><button className="btn" disabled={!page || busy} onClick={() => setPage(page - 1)}>{S.previous}</button><span>{page + 1} / {Math.ceil(cues.length / 25)}</span><button className="btn" disabled={(page + 1) * 25 >= cues.length || busy} onClick={() => setPage(page + 1)}>{S.next}</button></nav>}
        <footer className="subtitle-export"><div><h3>{S.deliver}</h3><p>{S.review}</p><div className="subtitle-toolbar">
          {(["srt", "vtt"] as const).map((format) => <button key={format} className="btn primary" disabled={busy || !valid}
            onClick={() => void action(() => download("export", { cues, format }, `subtitles.${format}`))}>{S.export} {format.toUpperCase()}</button>)}
        </div></div><div><label className="subtitle-check"><input type="checkbox" name="approve-render" checked={renderApproved} disabled={busy} onChange={(e) => setRenderApproved(e.target.checked)} />{S.renderApprove}</label>
          <button className="btn" disabled={busy || !valid || !renderApproved || !video || !status?.ffmpeg || !status.ffprobe}
            onClick={() => void action(() => download("burn", { cues, path, project_id: projectId, approved: true }, "subtitled.mp4"))}>{S.render}</button></div></footer>
      </>}
    </dialog>
  );
}
