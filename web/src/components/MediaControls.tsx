import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "../api";
import { t } from "../i18n";
import { base64Audio, recordWav, resizeImage, type SpeechStatus } from "../media";

/** Composer attachments are kept in browser memory until Send. Speech requires a saved opt-in and a click. */
export function MediaControls({ children, images, setImages, onDictation, busy, onPending }: {
  children?: ReactNode; images: string[]; setImages: (images: string[]) => void; onDictation: (text: string) => void;
  busy: boolean; onPending?: (pending: boolean) => void;
}) {
  const [status, setStatus] = useState<SpeechStatus | null>(null), [error, setError] = useState("");
  const [working, setWorking] = useState(false), [recording, setRecording] = useState(false);
  const recorder = useRef<Awaited<ReturnType<typeof recordWav>> | null>(null);
  const mounted = useRef(true), attaching = useRef(false), busyRef = useRef(busy);
  busyRef.current = busy;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; recorder.current?.cancel(); }; }, []);
  useEffect(() => { if (busy) { recorder.current?.cancel(); recorder.current = null; setRecording(false); } }, [busy]);
  useEffect(() => {
    if (!recording) return;
    const timer = setTimeout(() => {
      recorder.current?.cancel(); recorder.current = null; setRecording(false); setError(t.media.limit);
    }, 120_000);
    return () => clearTimeout(timer);
  }, [recording]);
  const attach = async (files: File[]) => {
    if (busy || attaching.current) return;
    if (files.length + images.length > 4) { setError(t.media.invalid); return; }
    attaching.current = true; onPending?.(true); setError("");
    try { const urls = await Promise.all(files.map(resizeImage)); if (mounted.current) setImages([...images, ...urls]); }
    catch { setError(t.media.invalid); }
    finally { attaching.current = false; onPending?.(false); }
  };
  const action = async (fn: () => Promise<void>) => {
    setWorking(true); setError("");
    try { await fn(); } catch (e) { setError(e instanceof ApiError ? e.message : t.media.failed); }
    finally { if (mounted.current) setWorking(false); }
  };
  const transcribe = async (blob: Blob) => {
    if (blob.size > 8_000_000) throw new Error(t.media.invalid);
    const result = await api.post<{ text: string }>("/api/media/transcribe", { audio: await base64Audio(blob) });
    if (mounted.current) onDictation(result.text);
  };
  return <div className="composer" onPaste={(e) => {
    const files = Array.from(e.clipboardData.files); if (files.length) { e.preventDefault(); void attach(files); }
  }} onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) e.preventDefault(); }}
    onDrop={(e) => { e.preventDefault(); void attach(Array.from(e.dataTransfer.files)); }}>
    {children}
    <div className="composer-bar">
      <label className="btn small">{t.media.image}<input type="file" accept="image/png,image/jpeg,image/webp" multiple
        className="sr-only" disabled={busy} onChange={(e) => { void attach(Array.from(e.target.files ?? [])); e.target.value = ""; }} /></label>
      <button type="button" className="btn small" data-voice-settings disabled={busy || working}
        onClick={() => { if (status) { recorder.current?.cancel(); recorder.current = null; setRecording(false); setStatus(null); }
          else void action(async () => setStatus(await api.get<SpeechStatus>("/api/media"))); }}>{t.media.voice}</button>
      <span className="small muted">{t.media.hint}</span>
    </div>
    {images.length > 0 && <div className="composer-bar">{images.map((image, i) => <div key={i}>
      <img src={image} alt={`${t.media.image} ${i + 1}`} width={72} height={54} style={{ objectFit: "contain" }} />
      <button type="button" className="btn small" disabled={busy} aria-label={`${t.media.remove} ${i + 1}`}
        onClick={() => setImages(images.filter((_, n) => n !== i))}>{t.media.remove}</button>
    </div>)}</div>}
    {status && <fieldset disabled={busy || working}>
      <legend>{t.media.voice}</legend><p className="small">{t.media.local}</p>
      <label><input type="checkbox" disabled={recording} checked={status.enabled} onChange={(e) => setStatus({ ...status, enabled: e.target.checked })} />{t.media.enable}</label>
      {(["whisper_model", "piper_model", "piper_license"] as const).map((key) => <label key={key} style={{ display: "block" }}>
        {t.media[key]}<input value={status[key]} onChange={(e) => setStatus({ ...status, [key]: e.target.value })} /></label>)}
      <button type="button" className="btn small" disabled={recording} onClick={() => void action(async () => setStatus(await api.put<SpeechStatus>("/api/media/settings", status)))}>{t.media.save}</button>
      <p className="small">whisper.cpp: {status.whisper ? t.media.installed : t.media.missing} · Piper: {status.piper ? t.media.installed : t.media.missing}</p>
      {status.license && <pre style={{ maxHeight: 120, overflow: "auto", whiteSpace: "pre-wrap" }}>{status.license}</pre>}
      <button type="button" className="btn small" disabled={!status.enabled || !status.whisper} onClick={() => void action(async () => {
        if (recorder.current) {
          const current = recorder.current; recorder.current = null; setRecording(false); await transcribe(await current.stop());
        } else {
          const current = await recordWav();
          if (!mounted.current || busyRef.current) { current.cancel(); return; }
          recorder.current = current; setRecording(true);
        }
      })}>{recording ? t.media.stop : t.media.dictate}</button>
      <label className="btn small">{t.media.wav}<input className="sr-only" type="file" accept="audio/wav,.wav" disabled={!status.enabled || !status.whisper}
        onChange={(e) => { const file = e.target.files?.[0]; if (file) void action(() => transcribe(file)); e.target.value = ""; }} /></label>
    </fieldset>}
    {error && <p role="alert" className="warn-text small">{error}</p>}
  </div>;
}
